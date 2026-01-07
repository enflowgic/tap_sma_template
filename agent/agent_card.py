"""
TAP Template Agent - A2A Agent Card

This file defines your agent's A2A-compliant metadata for discovery
and registration on the TAP mesh.

The Agent Card is the core metadata document that makes your agent
discoverable and interoperable with other A2A-compliant agents.

TODO: Customize all fields for your agent.
"""

import os
from typing import Optional

from tap_core.a2a import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    AgentProvider,
    AgentPricing,
    InputMode,
)

from .input_schema import AgentInputSchema
from .output_schema import AgentOutputSchema


# =============================================================================
# HELPERS
# =============================================================================

def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable with fallback."""
    return os.environ.get(key, default)


def _get_env_float(key: str, default: float) -> float:
    """Get environment variable as float."""
    value = os.environ.get(key)
    return float(value) if value else default


def _get_env_int(key: str, default: int) -> int:
    """Get environment variable as int."""
    value = os.environ.get(key)
    return int(value) if value else default


# =============================================================================
# AGENT CARD DEFINITION
# =============================================================================

AGENT_CARD = AgentCard(
    # =========================================================================
    # IDENTITY (Required)
    # =========================================================================

    # URL-safe slug - must be unique on the TAP mesh
    name="my-agent",  # TODO: Change to your agent's unique slug

    # Human-readable display name
    displayName="My Agent",  # TODO: Change to your display name

    # Description for semantic search in agent discovery
    description=(
        "A TAP-compatible template agent. "
        "TODO: Replace with your agent's description."
    ),

    # Semantic version
    version="1.0.0",

    # A2A protocol version
    protocolVersion="1.0",

    # =========================================================================
    # PROVIDER INFO
    # =========================================================================

    provider=AgentProvider(
        organization=_get_env("TAP_DEVELOPER_ORG", "My Company"),
        url=_get_env("TAP_DEVELOPER_URL"),
        email=_get_env("TAP_DEVELOPER_EMAIL"),
    ),

    documentationUrl=_get_env("TAP_AGENT_DOCS_URL"),
    iconUrl=_get_env("TAP_AGENT_ICON_URL"),

    # =========================================================================
    # CAPABILITIES
    # =========================================================================

    capabilities=AgentCapabilities(
        streaming=True,
        pushNotifications=False,
        stateTransitionHistory=True,
    ),

    # =========================================================================
    # SKILLS
    # =========================================================================

    skills=[
        AgentSkill(
            id="main-skill",  # TODO: Change to your skill ID
            name="Main Skill",  # TODO: Change to your skill name
            description=(
                "TODO: Describe what this skill does. "
                "This is used for semantic search."
            ),
            tags=["template", "example"],  # TODO: Add relevant tags
            examples=[
                "Help me with X",
                "Process this Y",
            ],  # TODO: Add example prompts
            inputModes=[InputMode.TEXT, InputMode.DATA],
            outputModes=[InputMode.TEXT, InputMode.DATA],
        ),
    ],

    # =========================================================================
    # SCHEMAS
    # =========================================================================

    defaultInputModes=[InputMode.TEXT],
    defaultOutputModes=[InputMode.TEXT, InputMode.DATA],
    inputSchema=AgentInputSchema.model_json_schema(),
    outputSchema=AgentOutputSchema.model_json_schema(),

    # =========================================================================
    # PRICING
    # =========================================================================

    pricing=AgentPricing(
        sales_price_per_1k_tokens=_get_env_float("TAP_PRICING_PER_1K", 0.003),
        estimated_tokens_per_task=_get_env_int("TAP_EST_TOKENS", 2500),
        currency="USD",
    ),
)


__all__ = ["AGENT_CARD"]
