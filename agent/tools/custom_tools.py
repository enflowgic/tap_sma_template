"""
TAP Template Agent - Custom Tools

Your agent-specific tools. Tools are Python functions with docstrings
that describe their purpose and parameters.

The docstring is used by the LLM to understand when and how to use the tool.

TODO: Replace these examples with your actual tools.
"""

import json
import logging
from typing import Optional

# Configure logging
logger = logging.getLogger(__name__)


# =============================================================================
# EXAMPLE TOOL
# =============================================================================

def example_tool(query: str, limit: int = 5) -> str:
    """
    An example tool that demonstrates the tool pattern.

    Replace this with your actual tool implementation.

    Args:
        query: The search query or input to process
        limit: Maximum number of results to return (default 5)

    Returns:
        JSON string containing the results
    """
    logger.info(f"example_tool called: query='{query}', limit={limit}")

    # TODO: Replace with your actual implementation
    results = {
        "status": "success",
        "query": query,
        "results": [
            {"id": i, "data": f"Result {i} for '{query}'"}
            for i in range(1, min(limit + 1, 6))
        ],
    }

    return json.dumps(results, indent=2)


# =============================================================================
# ADD YOUR TOOLS BELOW
# =============================================================================

# Example: Database tool
# def search_database(query: str, table: str = "default") -> str:
#     """
#     Search the database for records matching the query.
#
#     Args:
#         query: Search query
#         table: Table to search (default: "default")
#
#     Returns:
#         JSON string of matching records
#     """
#     # Your implementation here
#     pass


# Example: API tool
# def call_api(endpoint: str, method: str = "GET") -> str:
#     """
#     Call an external API endpoint.
#
#     Args:
#         endpoint: API endpoint path
#         method: HTTP method (GET, POST)
#
#     Returns:
#         JSON string of the API response
#     """
#     # Your implementation here
#     pass


# =============================================================================
# TOOL LIST
# =============================================================================

# Export your tools in this list
custom_tools = [
    example_tool,
    # Add your tools here
]


__all__ = [
    "example_tool",
    "custom_tools",
]
