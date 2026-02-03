"""
TAP Wrapper - Transfer Mock

Mock/stub for local testing without Gateway.
Simulates transfer_to_agent and agent_lookup responses for testing agent logic.

Enable with: TAP_USE_MOCK_TRANSFER=true

This allows you to test your agent's transfer logic locally without
needing a real Gateway or other SMAs running.
"""

import os
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Enable mock via environment variable
USE_MOCK = os.environ.get("TAP_USE_MOCK_TRANSFER", "false").lower() == "true"


# =============================================================================
# MOCK RESPONSES
# =============================================================================

# Configure mock responses for different agent slugs
MOCK_RESPONSES: Dict[str, Dict[str, Any]] = {
    # Default response for unknown agents
    "__default__": {
        "status": "success",
        "output": "Mock response from simulated agent",
        "input_tokens": 100,
        "output_tokens": 200,
    },

    # Example: Tax specialist mock
    "tax-specialist": {
        "status": "success",
        "output": "Based on the information provided, here are my tax recommendations...",
        "data": {
            "deductions_found": 3,
            "estimated_refund": 1500.00,
        },
        "input_tokens": 500,
        "output_tokens": 800,
    },

    # Example: Code reviewer mock
    "code-reviewer": {
        "status": "success",
        "output": "Code review complete. Found 2 issues and 5 suggestions.",
        "data": {
            "issues": ["Missing error handling", "Potential memory leak"],
            "suggestions": ["Add type hints", "Use constants", "Add tests"],
        },
        "input_tokens": 1000,
        "output_tokens": 600,
    },

    # Add custom mock responses here
}


# =============================================================================
# MOCK LOOKUP RESPONSES
# =============================================================================

MOCK_AGENTS: Dict[str, Dict[str, Any]] = {
    "tax-specialist": {
        "slug": "tax-specialist",
        "display_name": "Tax Specialist",
        "description": "Expert in tax preparation and optimization",
        "tier": "primary",
        "similarity": 0.95,
    },
    "code-reviewer": {
        "slug": "code-reviewer",
        "display_name": "Code Reviewer",
        "description": "Automated code review and suggestions",
        "tier": "secondary",
        "similarity": 0.88,
    },
    "premium-advisor": {
        "slug": "premium-advisor",
        "display_name": "Premium Advisor",
        "description": "Premium consulting services",
        "tier": "tertiary",  # Requires approval
        "similarity": 0.75,
        "pricing": {"per_1k_tokens": 0.01},
    },
}


# =============================================================================
# MOCK FUNCTIONS
# =============================================================================

def mock_transfer_to_agent(
    target_agent_slug: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Mock transfer_to_agent for local testing.

    Returns a simulated response based on MOCK_RESPONSES.

    Args:
        target_agent_slug: The agent to transfer to
        message: The message to send
        context: Optional context data

    Returns:
        Simulated agent response
    """
    if not USE_MOCK:
        raise RuntimeError(
            "Mock transfer called but TAP_USE_MOCK_TRANSFER is not set. "
            "Set TAP_USE_MOCK_TRANSFER=true to enable mock mode."
        )

    logger.info(f"[MOCK] transfer_to_agent: {target_agent_slug}")

    # Get mock response
    response = MOCK_RESPONSES.get(
        target_agent_slug,
        MOCK_RESPONSES["__default__"]
    )

    # Include request info in response
    return {
        **response,
        "_mock": True,
        "_request": {
            "agent": target_agent_slug,
            "message": message[:100],  # Truncate
        },
    }


def mock_agent_lookup(
    query: str,
    tier: str = "all",
    limit: int = 5,
) -> Dict[str, Any]:
    """
    Mock agent_lookup for local testing.

    Returns simulated agent search results based on MOCK_AGENTS.

    Args:
        query: Search query
        tier: Tier filter (primary, secondary, tertiary, all)
        limit: Maximum results

    Returns:
        Simulated search results
    """
    if not USE_MOCK:
        raise RuntimeError(
            "Mock lookup called but TAP_USE_MOCK_TRANSFER is not set."
        )

    logger.info(f"[MOCK] agent_lookup: query='{query}', tier={tier}")

    # Filter by tier
    results = []
    for slug, agent in MOCK_AGENTS.items():
        if tier != "all" and agent.get("tier") != tier:
            continue
        results.append(agent)
        if len(results) >= limit:
            break

    return {
        "status": "success",
        "data": {
            "agents": results,
            "total": len(results),
            "query": query,
        },
        "_mock": True,
    }


def mock_ask_clarifying_questions(
    questions: list,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Mock ask_clarifying_questions for local testing.

    Returns an INPUT_REQUIRED intent (as real tool would).

    Args:
        questions: List of question definitions
        reason: Reason for asking

    Returns:
        INPUT_REQUIRED intent
    """
    if not USE_MOCK:
        raise RuntimeError(
            "Mock questions called but TAP_USE_MOCK_TRANSFER is not set."
        )

    logger.info(f"[MOCK] ask_clarifying_questions: {len(questions)} questions")

    return {
        "intent_type": "INPUT_REQUIRED",
        "data": {
            "questions": questions,
            "reason": reason,
        },
        "_mock": True,
    }


# =============================================================================
# INTEGRATION HELPER
# =============================================================================

def get_mock_tools():
    """
    Get mock tool functions if mock mode is enabled.

    Returns:
        Dict of mock tool functions, or empty dict if not enabled
    """
    if not USE_MOCK:
        return {}

    return {
        "transfer_to_agent": mock_transfer_to_agent,
        "agent_lookup": mock_agent_lookup,
        "ask_clarifying_questions": mock_ask_clarifying_questions,
    }


__all__ = [
    "USE_MOCK",
    "MOCK_RESPONSES",
    "MOCK_AGENTS",
    "mock_transfer_to_agent",
    "mock_agent_lookup",
    "mock_ask_clarifying_questions",
    "get_mock_tools",
]
