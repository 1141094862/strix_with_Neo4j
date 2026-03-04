import inspect
import os
from typing import Any

import httpx


if os.getenv("STRIX_SANDBOX_MODE", "false").lower() == "false":
    from strix.runtime import get_runtime

from .argument_parser import convert_arguments
from .registry import (
    get_tool_by_name,
    get_tool_names,
    needs_agent_state,
    should_execute_in_sandbox,
)


SANDBOX_EXECUTION_TIMEOUT = float(os.getenv("STRIX_SANDBOX_EXECUTION_TIMEOUT", "120"))
SANDBOX_CONNECT_TIMEOUT = float(os.getenv("STRIX_SANDBOX_CONNECT_TIMEOUT", "10"))


async def execute_tool(tool_name: str, agent_state: Any | None = None, **kwargs: Any) -> Any:
    execute_in_sandbox = should_execute_in_sandbox(tool_name)
    sandbox_mode = os.getenv("STRIX_SANDBOX_MODE", "false").lower() == "true"

    if execute_in_sandbox and not sandbox_mode:
        return await _execute_tool_in_sandbox(tool_name, agent_state, **kwargs)

    return await _execute_tool_locally(tool_name, agent_state, **kwargs)


async def _execute_tool_in_sandbox(tool_name: str, agent_state: Any, **kwargs: Any) -> Any:
    if not hasattr(agent_state, "sandbox_id") or not agent_state.sandbox_id:
        raise ValueError("Agent state with a valid sandbox_id is required for sandbox execution.")

    if not hasattr(agent_state, "sandbox_token") or not agent_state.sandbox_token:
        raise ValueError(
            "Agent state with a valid sandbox_token is required for sandbox execution."
        )

    if (
        not hasattr(agent_state, "sandbox_info")
        or "tool_server_port" not in agent_state.sandbox_info
    ):
        raise ValueError(
            "Agent state with a valid sandbox_info containing tool_server_port is required."
        )

    runtime = get_runtime()
    tool_server_port = agent_state.sandbox_info["tool_server_port"]
    server_url = await runtime.get_sandbox_url(agent_state.sandbox_id, tool_server_port)
    request_url = f"{server_url}/execute"

    agent_id = getattr(agent_state, "agent_id", "unknown")

    request_data = {
        "agent_id": agent_id,
        "tool_name": tool_name,
        "kwargs": kwargs,
    }

    headers = {
        "Authorization": f"Bearer {agent_state.sandbox_token}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(
        timeout=SANDBOX_EXECUTION_TIMEOUT,
        connect=SANDBOX_CONNECT_TIMEOUT,
    )

    async with httpx.AsyncClient(trust_env=False) as client:
        try:
            response = await client.post(
                request_url, json=request_data, headers=headers, timeout=timeout
            )
            response.raise_for_status()
            response_data = response.json()
            if response_data.get("error"):
                raise RuntimeError(f"Sandbox execution error: {response_data['error']}")
            return response_data.get("result")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise RuntimeError("Authentication failed: Invalid or missing sandbox token") from e
            raise RuntimeError(f"HTTP error calling tool server: {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"Request error calling tool server: {e}") from e


async def _execute_tool_locally(tool_name: str, agent_state: Any | None, **kwargs: Any) -> Any:
    tool_func = get_tool_by_name(tool_name)
    if not tool_func:
        raise ValueError(f"Tool '{tool_name}' not found")

    converted_kwargs = convert_arguments(tool_func, kwargs)

    if needs_agent_state(tool_name):
        if agent_state is None:
            raise ValueError(f"Tool '{tool_name}' requires agent_state but none was provided.")
        result = tool_func(agent_state=agent_state, **converted_kwargs)
    else:
        result = tool_func(**converted_kwargs)

    return await result if inspect.isawaitable(result) else result


def validate_tool_availability(tool_name: str | None) -> tuple[bool, str]:
    if tool_name is None:
        return False, "Tool name is missing"

    if tool_name not in get_tool_names():
        return False, f"Tool '{tool_name}' is not available"

    return True, ""


async def execute_tool_with_validation(
    tool_name: str | None, agent_state: Any | None = None, **kwargs: Any
) -> Any:
    is_valid, error_msg = validate_tool_availability(tool_name)
    if not is_valid:
        return f"Error: {error_msg}"

    assert tool_name is not None

    try:
        result = await execute_tool(tool_name, agent_state, **kwargs)
    except Exception as e:  # noqa: BLE001
        error_str = str(e)
        if len(error_str) > 500:
            error_str = error_str[:500] + "... [truncated]"
        return f"Error executing {tool_name}: {error_str}"
    else:
        return result


async def execute_tool_invocation(tool_inv: dict[str, Any], agent_state: Any | None = None) -> Any:
    tool_name = tool_inv.get("toolName")
    tool_args = tool_inv.get("args", {})

    return await execute_tool_with_validation(tool_name, agent_state, **tool_args)


def _check_error_result(result: Any) -> tuple[bool, Any]:
    is_error = False
    error_payload: Any = None

    if (isinstance(result, dict) and "error" in result) or (
        isinstance(result, str) and result.strip().lower().startswith("error:")
    ):
        is_error = True
        error_payload = result

    return is_error, error_payload


def _update_tracer_with_result(
    tracer: Any, execution_id: Any, is_error: bool, result: Any, error_payload: Any
) -> None:
    if not tracer or not execution_id:
        return

    try:
        if is_error:
            tracer.update_tool_execution(execution_id, "error", error_payload)
        else:
            tracer.update_tool_execution(execution_id, "completed", result)
    except (ConnectionError, RuntimeError) as e:
        error_msg = str(e)
        if tracer and execution_id:
            tracer.update_tool_execution(execution_id, "error", error_msg)
        raise


def _format_tool_result(tool_name: str, result: Any) -> tuple[str, list[dict[str, Any]]]:
    images: list[dict[str, Any]] = []

    screenshot_data = extract_screenshot_from_result(result)
    if screenshot_data:
        images.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{screenshot_data}"},
            }
        )
        result_str = remove_screenshot_from_result(result)
    else:
        result_str = result

    if result_str is None:
        final_result_str = f"Tool {tool_name} executed successfully"
    else:
        final_result_str = str(result_str)
        if len(final_result_str) > 10000:
            start_part = final_result_str[:4000]
            end_part = final_result_str[-4000:]
            final_result_str = start_part + "\n\n... [middle content truncated] ...\n\n" + end_part

    observation_xml = (
        f"<tool_result>\n<tool_name>{tool_name}</tool_name>\n"
        f"<result>{final_result_str}</result>\n</tool_result>"
    )

    return observation_xml, images


async def _execute_single_tool(
    tool_inv: dict[str, Any],
    agent_state: Any | None,
    tracer: Any | None,
    agent_id: str,
) -> tuple[str, list[dict[str, Any]], bool]:
    tool_name = tool_inv.get("toolName", "unknown")
    args = tool_inv.get("args", {})
    execution_id = None
    should_agent_finish = False

    if tracer:
        execution_id = tracer.log_tool_execution_start(agent_id, tool_name, args)

    try:
        result = await execute_tool_invocation(tool_inv, agent_state)

        is_error, error_payload = _check_error_result(result)

        if (
            tool_name in ("finish_scan", "agent_finish")
            and not is_error
            and isinstance(result, dict)
        ):
            if tool_name == "finish_scan":
                should_agent_finish = result.get("scan_completed", False)
            elif tool_name == "agent_finish":
                should_agent_finish = result.get("agent_completed", False)

        _update_tracer_with_result(tracer, execution_id, is_error, result, error_payload)

        # === [新增] 工具执行后自动存储发现 ===
        if not is_error and tracer:
            _auto_store_discovery(tool_name, args, result, tracer)

    except (ConnectionError, RuntimeError, ValueError, TypeError, OSError) as e:
        error_msg = str(e)
        if tracer and execution_id:
            tracer.update_tool_execution(execution_id, "error", error_msg)
        raise

    observation_xml, images = _format_tool_result(tool_name, result)
    return observation_xml, images, should_agent_finish


def _auto_store_discovery(
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    tracer: Any,
) -> None:
    """工具执行后自动存储发现到 Neo4j"""
    try:
        from strix.memory.neo4j_client import Neo4jClient

        neo4j = Neo4jClient.get_instance()
        if not neo4j.is_connected():
            return

        # 获取 target_url
        scan_config = getattr(tracer, "scan_config", None)
        if not scan_config or not scan_config.get("targets"):
            return

        target_url = None
        for target in scan_config.get("targets", []):
            if target.get("type") == "web_application":
                target_url = target.get("details", {}).get("target_url")
            elif target.get("type") == "ip_address":
                target_url = target.get("details", {}).get("target_ip")
            if target_url:
                break

        if not target_url:
            return

        # 存储 Target
        neo4j.store_target(target_url)

        # 根据工具类型存储发现
        if tool_name == "browser_action":
            _store_browser_discovery(neo4j, args, result, target_url)
        elif tool_name == "terminal_execute":
            _store_terminal_discovery(neo4j, args, result, target_url)
        elif tool_name == "python_action":
            _store_python_discovery(neo4j, args, result, target_url)

    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Auto-store discovery failed: {e}")


def _store_browser_discovery(
    neo4j: Any,
    args: dict[str, Any],
    result: Any,
    target_url: str,
) -> None:
    """存储浏览器工具发现的端点"""
    if not isinstance(result, dict):
        return

    action = args.get("action")
    url = args.get("url", "")

    # 存储 URL 访问记录
    if action in ("launch", "goto", "new_tab") and url:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path or "/"

        node_id = neo4j.store_finding(
            "Endpoint",
            {
                "path": path,
                "method": "GET",
                "url": url,
                "source": "browser",
            },
        )
        if node_id:
            neo4j.create_relationship(node_id, "Endpoint", target_url, "Target", "DISCOVERED_IN")
            print(f"[Neo4j] ✅ Auto-stored Endpoint from browser: {path}")


def _store_terminal_discovery(
    neo4j: Any,
    args: dict[str, Any],
    result: Any,
    target_url: str,
) -> None:
    """存储终端工具发现的子域名和服务"""
    if not isinstance(result, dict):
        return

    command = args.get("command", "")
    content = result.get("content", "") or str(result)

    # 检测子域名枚举
    if "subfinder" in command or "subdomain" in command.lower():
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line and "." in line and not line.startswith("#"):
                node_id = neo4j.store_finding(
                    "Subdomain",
                    {"hostname": line, "source": "terminal"},
                )
                if node_id:
                    neo4j.create_relationship(node_id, "Subdomain", target_url, "Target", "DISCOVERED_IN")
        if lines:
            print(f"[Neo4j] ✅ Auto-stored Subdomains from terminal")

    # 检测端口扫描
    if "nmap" in command or "naabu" in command:
        import re
        port_pattern = r"(\d+)/tcp\s+open"
        ports = re.findall(port_pattern, content)
        for port in ports:
            node_id = neo4j.store_finding(
                "Service",
                {"port": int(port), "protocol": "tcp", "state": "open", "source": "terminal"},
            )
            if node_id:
                neo4j.create_relationship(node_id, "Service", target_url, "Target", "DISCOVERED_IN")
        if ports:
            print(f"[Neo4j] ✅ Auto-stored Services from terminal: {len(ports)} ports")


def _store_python_discovery(
    neo4j: Any,
    args: dict[str, Any],
    result: Any,
    target_url: str,
) -> None:
    """存储 Python 工具发现的凭证"""
    if not isinstance(result, dict):
        return

    content = result.get("stdout", "") or result.get("result", "") or str(result)

    # 检测凭证模式
    import re
    patterns = [
        (r"password[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']", "password"),
        (r"token[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']", "token"),
        (r"api_key[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']", "api_key"),
        (r"secret[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']", "secret"),
    ]

    for pattern, cred_type in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            if len(match) > 3:  # 忽略太短的值
                node_id = neo4j.store_finding(
                    "Credential",
                    {"type": cred_type, "value": match, "source": "python"},
                )
                if node_id:
                    neo4j.create_relationship(node_id, "Credential", target_url, "Target", "DISCOVERED_IN")
                print(f"[Neo4j] ✅ Auto-stored Credential from python: {cred_type}")


def _get_tracer_and_agent_id(agent_state: Any | None) -> tuple[Any | None, str]:
    try:
        from strix.telemetry.tracer import get_global_tracer

        tracer = get_global_tracer()
        agent_id = agent_state.agent_id if agent_state else "unknown_agent"
    except (ImportError, AttributeError):
        tracer = None
        agent_id = "unknown_agent"

    return tracer, agent_id


async def process_tool_invocations(
    tool_invocations: list[dict[str, Any]],
    conversation_history: list[dict[str, Any]],
    agent_state: Any | None = None,
) -> bool:
    observation_parts: list[str] = []
    all_images: list[dict[str, Any]] = []
    should_agent_finish = False

    tracer, agent_id = _get_tracer_and_agent_id(agent_state)

    for tool_inv in tool_invocations:
        observation_xml, images, tool_should_finish = await _execute_single_tool(
            tool_inv, agent_state, tracer, agent_id
        )
        observation_parts.append(observation_xml)
        all_images.extend(images)

        if tool_should_finish:
            should_agent_finish = True

    if all_images:
        content = [{"type": "text", "text": "Tool Results:\n\n" + "\n\n".join(observation_parts)}]
        content.extend(all_images)
        conversation_history.append({"role": "user", "content": content})
    else:
        observation_content = "Tool Results:\n\n" + "\n\n".join(observation_parts)
        conversation_history.append({"role": "user", "content": observation_content})

    return should_agent_finish


def extract_screenshot_from_result(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None

    screenshot = result.get("screenshot")
    if isinstance(screenshot, str) and screenshot:
        return screenshot

    return None


def remove_screenshot_from_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result

    result_copy = result.copy()
    if "screenshot" in result_copy:
        result_copy["screenshot"] = "[Image data extracted - see attached image]"

    return result_copy
