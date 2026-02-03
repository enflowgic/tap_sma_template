"""
TAP Wrapper - A2A Agent Card Generation

Auto-generates the A2A-compliant Agent Card from tap-agent.yaml manifest.
Developers configure the manifest, this module handles the A2A format.
"""

import logging
import os
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel

from tap_core.a2a import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    AgentProvider,
    AgentPricing,
    InputMode,
)

from .config import get_config, AgentConfig
from .manifest import load_manifest_dict

logger = logging.getLogger(__name__)


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


def generate_agent_card(
    input_schema: Optional[Type[BaseModel]] = None,
    output_schema: Optional[Type[BaseModel]] = None,
    config: Optional[AgentConfig] = None,
) -> AgentCard:
    """
    Generate A2A Agent Card from configuration.

    This auto-generates the Agent Card from tap-agent.yaml manifest,
    removing the need for developers to manage A2A-specific code.

    Args:
        input_schema: Input schema class (optional - uses schema from manifest)
        output_schema: Output schema class (optional)
        config: Agent configuration (optional - loads from manifest if None)

    Returns:
        AgentCard instance
    """
    if config is None:
        config = get_config()

    # Build skills from config
    skills = [
        AgentSkill(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            tags=skill.tags or config.tags,
            examples=skill.examples,
            inputModes=[InputMode.TEXT, InputMode.DATA],
            outputModes=[InputMode.TEXT, InputMode.DATA],
        )
        for skill in config.skills
    ]

    # If no skills defined, create a default one
    if not skills:
        skills = [
            AgentSkill(
                id="main-skill",
                name=config.display_name,
                description=config.description,
                tags=config.tags,
                examples=[],
                inputModes=[InputMode.TEXT, InputMode.DATA],
                outputModes=[InputMode.TEXT, InputMode.DATA],
            )
        ]

    # Build the agent card
    card = AgentCard(
        # Identity
        name=config.slug,
        displayName=config.display_name,
        description=config.description,
        version=config.version,
        protocolVersion="1.0",

        # Provider
        provider=AgentProvider(
            organization=config.provider.organization_name,
            url=config.provider.url,
            email=config.provider.support_email,
        ),

        documentationUrl=_get_env("TAP_AGENT_DOCS_URL"),
        iconUrl=_get_env("TAP_AGENT_ICON_URL"),

        # Capabilities
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=True,
        ),

        # Skills
        skills=skills,

        # I/O Modes
        defaultInputModes=[InputMode.TEXT],
        defaultOutputModes=[InputMode.TEXT, InputMode.DATA],

        # Schemas (if provided)
        inputSchema=input_schema.model_json_schema() if input_schema else None,
        outputSchema=output_schema.model_json_schema() if output_schema else None,

        # Pricing (from environment or defaults)
        pricing=AgentPricing(
            sales_price_per_1k_tokens=_get_env_float("TAP_PRICING_PER_1K", 0.003),
            estimated_tokens_per_task=_get_env_int("TAP_EST_TOKENS", 2500),
            currency="USD",
        ),

        # System Manifest (for TapInitialiserAgent and personalization)
        # Loads the complete system-manifest.yaml contents for agent introspection
        systemManifest=load_manifest_dict() or None,
    )

    return card


def get_agent_card_dict(
    input_schema: Optional[Type[BaseModel]] = None,
    output_schema: Optional[Type[BaseModel]] = None,
) -> Dict[str, Any]:
    """
    Get Agent Card as dictionary (for JSON serialization).

    Args:
        input_schema: Input schema class (optional)
        output_schema: Output schema class (optional)

    Returns:
        Agent Card as dictionary
    """
    card = generate_agent_card(input_schema, output_schema)
    return card.model_dump(exclude_none=True)


# Lazy-loaded singleton
_agent_card: Optional[AgentCard] = None


def get_agent_card() -> AgentCard:
    """
    Get the agent card (singleton, lazy-loaded).

    Note: This version doesn't include schemas. Use generate_agent_card()
    with schema classes for full card generation.
    """
    global _agent_card
    if _agent_card is None:
        _agent_card = generate_agent_card()
    return _agent_card


__all__ = [
    "generate_agent_card",
    "get_agent_card",
    "get_agent_card_dict",
]
