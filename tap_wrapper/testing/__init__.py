"""
TAP Wrapper - Testing Utilities

Testing utilities for local development without Gateway.
Enable with: TAP_USE_MOCK_TRANSFER=true

These mocks allow testing agent transfer and lookup logic locally
without needing real Gateway or other SMAs running.
"""

from .mock_transfer import (
    USE_MOCK,
    MOCK_RESPONSES,
    MOCK_AGENTS,
    mock_transfer_to_agent,
    mock_agent_lookup,
    mock_ask_clarifying_questions,
    get_mock_tools,
)

__all__ = [
    "USE_MOCK",
    "MOCK_RESPONSES",
    "MOCK_AGENTS",
    "mock_transfer_to_agent",
    "mock_agent_lookup",
    "mock_ask_clarifying_questions",
    "get_mock_tools",
]
