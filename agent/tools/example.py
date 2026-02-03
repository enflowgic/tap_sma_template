"""
Example Tool Module

This demonstrates the tool pattern for TAP agents.
Delete this file and create your own tool modules.

Best practices (per Google ADK docs):
- Simple function signatures with few parameters
- Use basic types: str, int, float, bool, list, dict
- Clear docstrings with Args and Returns sections
- Return dict directly (ADK handles serialization)
- Keep tools focused - one tool = one capability
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def example_tool(query: str, limit: int = 5) -> Dict[str, Any]:
    """
    An example tool that demonstrates the tool pattern.

    Replace this with your actual tool implementation.

    Args:
        query: The search query or input to process
        limit: Maximum number of results to return (default 5)

    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - query: The original query
        - results: List of result objects
    """
    logger.info(f"example_tool called: query='{query}', limit={limit}")

    # TODO: Replace with your actual implementation
    return {
        "status": "success",
        "query": query,
        "results": [
            {"id": i, "data": f"Result {i} for '{query}'"}
            for i in range(1, min(limit + 1, 6))
        ],
    }


__all__ = ["example_tool"]
