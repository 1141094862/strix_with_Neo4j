import logging
import os
from typing import Any

import litellm


logger = logging.getLogger(__name__)


MAX_TOTAL_TOKENS = 100_000
MIN_RECENT_MESSAGES = 15

SUMMARY_PROMPT_TEMPLATE = """You are compressing conversation history for a security agent.

=== NEO4J GRAPH MEMORY ===
Technical findings are stored in Neo4j graph database.
Your conversation may contain <neo4j_context> showing current known state.
You can also query memory using query_memory tool.

=== COMPRESSION PRINCIPLE (SEMI-CONSTRAINED) ===
You decide what to preserve based on operational needs.

MUST preserve (for continuity):
- Current phase and objective
- Critical decisions made
- Active sessions/credentials
- Blocking issues

SHOULD preserve (if relevant):
- Attack strategy and reasoning
- Failed approaches (to avoid repetition)
- Key insights about target
- Next planned steps

DO NOT preserve (available in Neo4j):
- Exact URLs, paths, parameters
- Vulnerability details and payloads
- Raw tool outputs
- Technical specifications

=== FORMAT (YOU DECIDE) ===
Use any structure that best captures the operational context:
- Can use XML tags, markdown, or plain text
- Can add any fields you find relevant
- Focus on WHAT the next agent needs to know

Example structures (you can modify or create your own):
<summary>
<phase>scanning</phase>
<objective>Test authentication</objective>
<key_insights>...</key_insights>
<decisions>...</decisions>
<next_steps>...</next_steps>
</summary>

Or simply:
Phase: scanning
Goal: Test auth
Key findings: [stored in Neo4j]
Next: Try SQLi on login form

CONVERSATION SEGMENT TO SUMMARIZE:
{conversation}

Provide a summary that helps the next agent continue effectively.
Keep it concise but operationally useful."""


def _count_tokens(text: str, model: str) -> int:
    try:
        count = litellm.token_counter(model=model, text=text)
        return int(count)
    except Exception:
        logger.exception("Failed to count tokens")
        return len(text) // 4  # Rough estimate


def _get_message_tokens(msg: dict[str, Any], model: str) -> int:
    content = msg.get("content", "")
    if isinstance(content, str):
        return _count_tokens(content, model)
    if isinstance(content, list):
        return sum(
            _count_tokens(item.get("text", ""), model)
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return 0


def _extract_message_text(msg: dict[str, Any]) -> str:
    content = msg.get("content", "")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "image_url":
                    parts.append("[IMAGE]")
        return " ".join(parts)

    return str(content)


def _summarize_messages(
    messages: list[dict[str, Any]],
    model: str,
    timeout: int = 600,
) -> dict[str, Any]:
    if not messages:
        empty_summary = "<context_summary message_count='0'>{text}</context_summary>"
        return {
            "role": "assistant",
            "content": empty_summary.format(text="No messages to summarize"),
        }

    formatted = []
    for msg in messages:
        role = msg.get("role", "unknown")
        text = _extract_message_text(msg)
        formatted.append(f"{role}: {text}")

    conversation = "\n".join(formatted)
    prompt = SUMMARY_PROMPT_TEMPLATE.format(conversation=conversation)

    try:
        completion_args = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "timeout": timeout,
        }

        response = litellm.completion(**completion_args)
        summary = response.choices[0].message.content or ""
        if not summary.strip():
            return messages[0]
        summary_msg = "<context_summary message_count='{count}'>{text}</context_summary>"
        return {
            "role": "assistant",
            "content": summary_msg.format(count=len(messages), text=summary),
        }
    except Exception:
        logger.exception("Failed to summarize messages")
        return messages[0]


def _handle_images(messages: list[dict[str, Any]], max_images: int) -> None:
    image_count = 0
    for msg in reversed(messages):
        content = msg.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    if image_count >= max_images:
                        item.update(
                            {
                                "type": "text",
                                "text": "[Previously attached image removed to preserve context]",
                            }
                        )
                    else:
                        image_count += 1


class MemoryCompressor:
    def __init__(
        self,
        max_images: int = 3,
        model_name: str | None = None,
        timeout: int = 600,
        target_url: str | None = None,
    ):
        self.max_images = max_images
        self.model_name = model_name or os.getenv("STRIX_LLM", "openai/gpt-5")
        self.timeout = timeout
        self.target_url = target_url

        if not self.model_name:
            raise ValueError("STRIX_LLM environment variable must be set and not empty")

    def _get_target_topology(self) -> str | None:
        """从 Neo4j 读取目标拓扑信息（展示所有属性）"""
        if not self.target_url:
            return None

        try:
            from strix.memory.neo4j_client import Neo4jClient

            neo4j = Neo4jClient.get_instance()
            if not neo4j.is_connected():
                logger.debug("Neo4j not connected, skipping topology retrieval")
                return None

            topology = neo4j.get_target_topology(self.target_url)
            if not topology:
                logger.debug(f"No topology data found for target: {self.target_url}")
                return None

            phase = self._determine_phase(topology)
            
            # 统计各类发现数量
            total_items = sum(len(topology.get(k, [])) for k in ["endpoints", "vulnerabilities", "subdomains", "technologies", "credentials", "parameters", "findings"])
            logger.info(f"✅ Retrieved topology from Neo4j for {self.target_url}: {total_items} items, phase={phase}")
            print(f"[Neo4j] 📖 Retrieved graph memory for {self.target_url}: {total_items} items, phase={phase}")

            lines = [
                f"<neo4j_context target=\"{self.target_url}\" phase=\"{phase}\">",
                "<!-- Graph Memory: All stored discoveries -->",
            ]

            # 展示所有属性（半约束：LLM 决定关注什么）
            for key in ["endpoints", "vulnerabilities", "subdomains", "technologies", "credentials", "parameters", "findings"]:
                items = topology.get(key, [])
                if items:
                    lines.append(f"  <{key}>")
                    for item in items:
                        # 展示所有属性
                        props_str = " ".join([f'{k}="{v}"' for k, v in item.items() if v is not None])
                        if props_str:
                            lines.append(f"    <item {props_str}/>")
                        else:
                            lines.append(f"    <item/>")
                    lines.append(f"  </{key}>")

            lines.append("</neo4j_context>")
            return "\n".join(lines)

        except Exception as e:
            logger.debug(f"Failed to get target topology from Neo4j: {e}")
            return None

    def _determine_phase(self, topology: dict[str, Any]) -> str:
        """根据拓扑信息判断当前阶段"""
        endpoints = topology.get("endpoints", [])
        vulns = topology.get("vulnerabilities", [])
        subdomains = topology.get("subdomains", [])
        credentials = topology.get("credentials", [])

        if credentials or (vulns and any(v.get("severity") in ["critical", "high"] for v in vulns)):
            return "exploitation"
        if vulns:
            return "post-exploitation"
        if len(endpoints) > 5:
            return "scanning"
        if subdomains or endpoints:
            return "recon"
        return "recon"

    def compress_history(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Compress conversation history to stay within token limits.

        Strategy:
        1. Handle image limits first
        2. Keep all system messages
        3. Keep minimum recent messages
        4. Summarize older messages when total tokens exceed limit

        The compression preserves:
        - All system messages unchanged
        - Most recent messages intact
        - Critical security context in summaries
        - Recent images for visual context
        - Technical details and findings
        """
        if not messages:
            return messages

        _handle_images(messages, self.max_images)

        system_msgs = []
        regular_msgs = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msgs.append(msg)
            else:
                regular_msgs.append(msg)

        recent_msgs = regular_msgs[-MIN_RECENT_MESSAGES:]
        old_msgs = regular_msgs[:-MIN_RECENT_MESSAGES]

        # Type assertion since we ensure model_name is not None in __init__
        model_name: str = self.model_name  # type: ignore[assignment]

        total_tokens = sum(
            _get_message_tokens(msg, model_name) for msg in system_msgs + regular_msgs
        )

        # === 始终注入 Neo4j 拓扑信息 ===
        topology_context = self._get_target_topology()
        if topology_context:
            topology_msg = {
                "role": "system",
                "content": topology_context,
            }
            system_msgs.append(topology_msg)

        if total_tokens <= MAX_TOTAL_TOKENS * 0.9:
            return system_msgs + regular_msgs

        compressed = []
        chunk_size = 10
        for i in range(0, len(old_msgs), chunk_size):
            chunk = old_msgs[i : i + chunk_size]
            summary = _summarize_messages(chunk, model_name, self.timeout)
            if summary:
                compressed.append(summary)

        return system_msgs + compressed + recent_msgs
