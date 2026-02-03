"""
TAP Template Agent - Custom Tools Package

This package contains your agent-specific tools. Organize your tools
across multiple files as your implementation grows.

Structure:
    tools/
    ├── __init__.py      # This file - exports custom_tools list
    ├── example.py       # Example tool (delete when ready)
    ├── search.py        # Your search tools
    ├── data/            # Data processing tools
    │   ├── __init__.py
    │   ├── parser.py
    │   └── transform.py
    └── external/        # External API integrations
        ├── __init__.py
        └── api_client.py

Usage in agent.py:
    from .tools import custom_tools

    agent = LlmAgent(
        tools=custom_tools,  # Mesh tools added automatically by tap_wrapper
        ...
    )
"""

from typing import List, Callable

# =============================================================================
# IMPORT YOUR TOOLS
# =============================================================================
# Add imports from your tool modules here

from .example import example_tool

# If you have tools in subdirectories:
# from .search import search_web, search_docs
# from .data import parse_csv, transform_json


# =============================================================================
# EXPORT TOOL LIST
# =============================================================================
# TAP wrapper will combine these with mesh tools automatically

custom_tools: List[Callable] = [
    example_tool,
    # Add your tools here:
    # search_web,
    # search_docs,
    # parse_csv,
]


__all__ = ["custom_tools", "example_tool"]
