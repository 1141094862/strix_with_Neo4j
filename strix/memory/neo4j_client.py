"""
Neo4j 客户端封装类
负责连接管理、核心节点存储、扩展节点存储、查询接口
"""

import logging
from typing import Any

from neo4j import GraphDatabase

from strix.runtime.docker_runtime import (
    NEO4J_BOLT_PORT,
    NEO4J_PASSWORD,
    NEO4J_USER,
)

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Neo4j 客户端单例类"""

    _instance: "Neo4jClient | None" = None
    _driver: Any = None

    @classmethod
    def get_instance(cls) -> "Neo4jClient":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        if Neo4jClient._driver is not None:
            return

        uri = f"bolt://127.0.0.1:{NEO4J_BOLT_PORT}"
        try:
            Neo4jClient._driver = GraphDatabase.driver(
                uri,
                auth=(NEO4J_USER, NEO4J_PASSWORD),
            )
            logger.info(f"Neo4j client connected to {uri}")
            self._create_constraints()
        except Exception as e:
            logger.warning(f"Failed to connect to Neo4j: {e}")
            Neo4jClient._driver = None

    def _create_constraints(self) -> None:
        """创建核心节点约束"""
        if Neo4jClient._driver is None:
            return

        constraints = [
            "CREATE CONSTRAINT target_url_unique IF NOT EXISTS FOR (t:Target) REQUIRE t.url IS UNIQUE",
            "CREATE CONSTRAINT vuln_id_unique IF NOT EXISTS FOR (v:Vulnerability) REQUIRE v.id IS UNIQUE",
            "CREATE CONSTRAINT agent_id_unique IF NOT EXISTS FOR (a:Agent) REQUIRE a.agent_id IS UNIQUE",
            "CREATE CONSTRAINT scan_run_id_unique IF NOT EXISTS FOR (s:ScanRun) REQUIRE s.run_id IS UNIQUE",
        ]

        with Neo4jClient._driver.session() as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    logger.debug(f"Constraint creation skipped: {e}")

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return Neo4jClient._driver is not None

    # === 核心节点存储（强约束）===

    def store_target(self, url: str, properties: dict[str, Any] | None = None) -> str:
        """存储目标节点"""
        if Neo4jClient._driver is None:
            return ""

        props = properties or {}
        props["url"] = url

        with Neo4jClient._driver.session() as session:
            result = session.run(
                "MERGE (t:Target {url: $url}) "
                "SET t += $props "
                "RETURN t.url",
                url=url,
                props=props,
            )
            record = result.single()
            return record["t.url"] if record else ""

    def store_vulnerability(
        self,
        vuln_id: str,
        vuln_type: str,
        severity: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """存储漏洞节点"""
        if Neo4jClient._driver is None:
            return ""

        props = properties or {}
        props["id"] = vuln_id
        props["type"] = vuln_type
        props["severity"] = severity

        with Neo4jClient._driver.session() as session:
            result = session.run(
                "MERGE (v:Vulnerability {id: $vuln_id}) "
                "SET v += $props "
                "RETURN v.id",
                vuln_id=vuln_id,
                props=props,
            )
            record = result.single()
            return record["v.id"] if record else ""

    def store_agent(self, agent_id: str, properties: dict[str, Any] | None = None) -> str:
        """存储 Agent 节点"""
        if Neo4jClient._driver is None:
            return ""

        props = properties or {}
        props["agent_id"] = agent_id

        with Neo4jClient._driver.session() as session:
            result = session.run(
                "MERGE (a:Agent {agent_id: $agent_id}) "
                "SET a += $props "
                "RETURN a.agent_id",
                agent_id=agent_id,
                props=props,
            )
            record = result.single()
            return record["a.agent_id"] if record else ""

    def store_scan_run(self, run_id: str, properties: dict[str, Any] | None = None) -> str:
        """存储扫描运行节点"""
        if Neo4jClient._driver is None:
            return ""

        props = properties or {}
        props["run_id"] = run_id

        with Neo4jClient._driver.session() as session:
            result = session.run(
                "MERGE (s:ScanRun {run_id: $run_id}) "
                "SET s += $props "
                "RETURN s.run_id",
                run_id=run_id,
                props=props,
            )
            record = result.single()
            return record["s.run_id"] if record else ""

    # === 扩展节点存储（灵活）===

    def store_finding(
        self,
        node_type: str,
        properties: dict[str, Any],
        relationships: list[dict[str, Any]] | None = None,
    ) -> str:
        """
        存储发现节点（灵活格式）

        Args:
            node_type: 节点类型（如 Endpoint, Parameter, Subdomain, Finding）
            properties: 节点属性（由 LLM 决定）
            relationships: 关系列表（由 LLM 决定）

        Returns:
            节点 ID
        """
        if Neo4jClient._driver is None:
            return ""

        node_id = properties.get("id") or properties.get("url") or properties.get("path") or ""

        with Neo4jClient._driver.session() as session:
            result = session.run(
                f"CREATE (n:{node_type} $props) RETURN elementId(n)",
                props=properties,
            )
            record = result.single()
            internal_id = record[0] if record else ""

            if relationships:
                for rel in relationships:
                    self._create_relationship_internal(
                        session, internal_id, node_type, rel
                    )

            # === [新增] 自动从 URL 提取 Target 并建立关系 ===
            url = properties.get("url") or properties.get("path")
            if url and url.startswith("http"):
                from urllib.parse import urlparse
                parsed = urlparse(url)
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                
                # 存储 Target
                self.store_target(base_url)
                
                # 建立关系
                try:
                    session.run(
                        f"MATCH (n:{node_type}) WHERE elementId(n) = $internal_id "
                        f"MATCH (t:Target {{url: $base_url}}) "
                        f"MERGE (n)-[:DISCOVERED_IN]->(t)",
                        internal_id=internal_id,
                        base_url=base_url,
                    )
                    logger.debug(f"Auto-linked {node_type} to Target: {base_url}")
                except Exception as e:
                    logger.debug(f"Failed to auto-link to target: {e}")

            return node_id or internal_id

    def _create_relationship_internal(
        self,
        session: Any,
        from_id: str,
        from_type: str,
        rel: dict[str, Any],
    ) -> None:
        """内部方法：创建关系"""
        try:
            target_type = rel.get("target_type", "")
            target_id = rel.get("target_id", "")
            rel_type = rel.get("relation_type", "RELATED_TO")

            session.run(
                f"MATCH (a:{from_type}) WHERE elementId(a) = $from_id "
                f"MATCH (b:{target_type}) WHERE elementId(b) = $to_id OR b.{target_type.lower()}_id = $to_id OR b.url = $to_id "
                f"MERGE (a)-[r:{rel_type}]->(b)",
                from_id=from_id,
                to_id=target_id,
            )
        except Exception as e:
            logger.debug(f"Failed to create relationship: {e}")

    # === 关系创建 ===

    def create_relationship(
        self,
        from_id: str,
        from_type: str,
        to_id: str,
        to_type: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """创建关系"""
        if Neo4jClient._driver is None:
            return

        # 确定属性名（Target 用 url，其他用 id 或 {type}_id）
        from_id_prop = "url" if from_type == "Target" else f"{from_type.lower()}_id"
        to_id_prop = "url" if to_type == "Target" else f"{to_type.lower()}_id"

        # 如果 ID 看起来像 URL，使用 url 属性
        if to_id and (to_id.startswith("http://") or to_id.startswith("https://")):
            to_id_prop = "url"

        with Neo4jClient._driver.session() as session:
            try:
                session.run(
                    f"MATCH (a:{from_type}) WHERE a.{from_id_prop} = $from_id OR a.id = $from_id "
                    f"MATCH (b:{to_type}) WHERE b.{to_id_prop} = $to_id OR b.url = $to_id OR b.id = $to_id "
                    f"MERGE (a)-[r:{rel_type}]->(b) "
                    "SET r += $props",
                    from_id=from_id,
                    to_id=to_id,
                    props=properties or {},
                )
            except Exception as e:
                logger.debug(f"Failed to create relationship: {e}")

    def link_vulnerability_to_target(
        self, vuln_id: str, target_url: str, endpoint_path: str | None = None
    ) -> None:
        """关联漏洞到目标"""
        if Neo4jClient._driver is None:
            return

        with Neo4jClient._driver.session() as session:
            if endpoint_path:
                session.run(
                    "MATCH (v:Vulnerability {id: $vuln_id}) "
                    "MATCH (t:Target {url: $target_url}) "
                    "MATCH (e:Endpoint {path: $endpoint_path}) "
                    "MERGE (e)-[:HAS_VULNERABILITY]->(v) "
                    "MERGE (t)-[:HAS_ENDPOINT]->(e)",
                    vuln_id=vuln_id,
                    target_url=target_url,
                    endpoint_path=endpoint_path,
                )
            else:
                session.run(
                    "MATCH (v:Vulnerability {id: $vuln_id}) "
                    "MATCH (t:Target {url: $target_url}) "
                    "MERGE (t)-[:HAS_VULNERABILITY]->(v)",
                    vuln_id=vuln_id,
                    target_url=target_url,
                )

    # === 查询接口 ===

    def get_target_topology(self, target_url: str) -> dict[str, Any]:
        """获取目标拓扑信息（返回所有属性）"""
        if Neo4jClient._driver is None:
            return {}

        with Neo4jClient._driver.session() as session:
            result = session.run(
                "MATCH (t:Target {url: $url}) "
                "OPTIONAL MATCH (t)-[r1]->(n1) "
                "OPTIONAL MATCH (n1)-[r2]->(n2) "
                "RETURN t, r1, n1, r2, n2",
                url=target_url,
            )

            topology: dict[str, Any] = {
                "target": target_url,
                "endpoints": [],
                "vulnerabilities": [],
                "subdomains": [],
                "technologies": [],
                "credentials": [],
                "parameters": [],
                "findings": [],
            }

            for record in result:
                n1 = record.get("n1")
                if n1:
                    labels = list(n1.labels) if hasattr(n1, "labels") else []
                    props = dict(n1) if n1 else {}

                    if "Endpoint" in labels:
                        topology["endpoints"].append(props)
                    elif "Vulnerability" in labels:
                        topology["vulnerabilities"].append(props)
                    elif "Subdomain" in labels:
                        topology["subdomains"].append(props)
                    elif "Technology" in labels:
                        topology["technologies"].append(props)
                    elif "Credential" in labels:
                        topology["credentials"].append(props)
                    elif "Parameter" in labels:
                        topology["parameters"].append(props)
                    else:
                        topology["findings"].append(props)

                n2 = record.get("n2")
                if n2:
                    labels = list(n2.labels) if hasattr(n2, "labels") else []
                    props = dict(n2) if n2 else {}

                    if "Endpoint" in labels and props not in topology["endpoints"]:
                        topology["endpoints"].append(props)
                    elif "Vulnerability" in labels and props not in topology["vulnerabilities"]:
                        topology["vulnerabilities"].append(props)
                    elif "Subdomain" in labels and props not in topology["subdomains"]:
                        topology["subdomains"].append(props)
                    elif "Technology" in labels and props not in topology["technologies"]:
                        topology["technologies"].append(props)
                    elif "Credential" in labels and props not in topology["credentials"]:
                        topology["credentials"].append(props)
                    elif "Parameter" in labels and props not in topology["parameters"]:
                        topology["parameters"].append(props)
                    elif props not in topology["findings"]:
                        topology["findings"].append(props)

            return topology

    def get_vulnerabilities(self, target_url: str | None = None) -> list[dict[str, Any]]:
        """获取漏洞列表"""
        if Neo4jClient._driver is None:
            return []

        with Neo4jClient._driver.session() as session:
            if target_url:
                result = session.run(
                    "MATCH (t:Target {url: $url})-[:HAS_VULNERABILITY|:HAS_ENDPOINT*]->(v:Vulnerability) "
                    "RETURN v",
                    url=target_url,
                )
            else:
                result = session.run("MATCH (v:Vulnerability) RETURN v")

            return [dict(record["v"]) for record in result if record.get("v")]

    def get_agent_discoveries(self, agent_id: str) -> list[dict[str, Any]]:
        """获取 Agent 的发现"""
        if Neo4jClient._driver is None:
            return []

        with Neo4jClient._driver.session() as session:
            result = session.run(
                "MATCH (a:Agent {agent_id: $agent_id})-[:DISCOVERED]->(n) "
                "RETURN n",
                agent_id=agent_id,
            )

            return [dict(record["n"]) for record in result if record.get("n")]

    def query_by_type(self, node_type: str, target_url: str | None = None) -> list[dict[str, Any]]:
        """按类型查询节点（灵活查询）"""
        if Neo4jClient._driver is None:
            return []

        type_mapping = {
            "endpoint": "Endpoint",
            "endpoints": "Endpoint",
            "parameter": "Parameter",
            "parameters": "Parameter",
            "subdomain": "Subdomain",
            "subdomains": "Subdomain",
            "vulnerability": "Vulnerability",
            "vulnerabilities": "Vulnerability",
            "credential": "Credential",
            "credentials": "Credential",
            "technology": "Technology",
            "technologies": "Technology",
            "finding": "Finding",
            "findings": "Finding",
            "target": "Target",
            "targets": "Target",
            "all": None,  # 查询所有
            "all discoveries": None,
        }

        label = type_mapping.get(node_type.lower(), None)

        with Neo4jClient._driver.session() as session:
            if label is None:
                # 查询所有节点
                if target_url:
                    result = session.run(
                        "MATCH (t:Target {url: $url})-[r]->(n) "
                        "WHERE NOT n:Target "
                        "RETURN labels(n) as labels, n as node",
                        url=target_url,
                    )
                else:
                    result = session.run(
                        "MATCH (n) WHERE NOT n:Target RETURN labels(n) as labels, n as node"
                    )
                return [{"labels": record["labels"], **dict(record["node"])} for record in result if record.get("node")]
            else:
                if target_url:
                    result = session.run(
                        f"MATCH (t:Target {{url: $url}})-[r]->(n:{label}) "
                        "RETURN n",
                        url=target_url,
                    )
                else:
                    result = session.run(f"MATCH (n:{label}) RETURN n")

                return [dict(record["n"]) for record in result if record.get("n")]

    def close(self) -> None:
        """关闭连接"""
        if Neo4jClient._driver:
            Neo4jClient._driver.close()
            Neo4jClient._driver = None
            logger.info("Neo4j connection closed")
