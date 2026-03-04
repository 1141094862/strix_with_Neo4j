"""Memory actions for Neo4j graph storage."""

from typing import Any

from strix.tools.registry import register_tool


@register_tool(sandbox_execution=False)
def query_memory(
    agent_state: Any,
    query: str,
    target: str | None = None,
) -> dict[str, Any]:
    """
    Query Neo4j graph memory for previously stored discoveries.

    Use this tool to retrieve information about endpoints, vulnerabilities,
    subdomains, technologies, credentials, and other findings stored in the
    graph database.

    Args:
        agent_state: Agent state (injected automatically)
        query: What to search for. Supported types:
               - "endpoints" or "endpoint": Web endpoints/URLs
               - "vulnerabilities" or "vulnerability": Security issues found
               - "subdomains" or "subdomain": Discovered subdomains
               - "technologies" or "technology": Tech stack information
               - "credentials" or "credential": Found credentials/secrets
               - "all": All stored discoveries
        target: Optional target URL to filter results by specific target

    Returns:
        Dictionary with success status, results list, and count
    """
    try:
        from strix.memory.neo4j_client import Neo4jClient

        neo4j = Neo4jClient.get_instance()
        if not neo4j.is_connected():
            return {
                "success": False,
                "error": "Neo4j not connected",
                "results": [],
                "count": 0,
            }

        results = neo4j.query_by_type(query, target)
        
        print(f"[Neo4j] 🔍 Queried graph memory for '{query}': found {len(results)} results")
        
        return {
            "success": True,
            "results": results,
            "count": len(results),
            "query": query,
            "target": target,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "results": [],
            "count": 0,
        }
