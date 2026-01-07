"""
TAP Template Agent - Agent Package

This package contains your agent definition, schemas, tools, and configuration.

Exports:
- root_agent: The main agent runnable (LlmAgent)
- AGENT_CARD: A2A Agent Card for discovery
- AgentInputSchema: Input contract
- AgentOutputSchema: Output contract
- SYSTEM_PROMPT: System prompt configuration
"""

from .definition import (
    root_agent,
    AGENT_RUNNABLE,
    AGENT_NAME,
    AGENT_METADATA,
)
from .agent_card import AGENT_CARD
from .input_schema import AgentInputSchema
from .output_schema import AgentOutputSchema
from .prompts import SYSTEM_PROMPT, PROMPTS

__all__ = [
    # Agent
    "root_agent",
    "AGENT_RUNNABLE",
    "AGENT_NAME",
    "AGENT_METADATA",
    # A2A
    "AGENT_CARD",
    # Schemas
    "AgentInputSchema",
    "AgentOutputSchema",
    # Prompts
    "SYSTEM_PROMPT",
    "PROMPTS",
]
