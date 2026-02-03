"""
TAP Wrapper - Platform Integration Layer

This package provides automatic TAP platform integration for developer agents.
Developers write pure Google ADK agents, and this wrapper handles:

1. Mesh tools injection (12 universal tools)
2. Input validation wrapping
3. Personalization via TapInitialiserAgent (reads system_manifest.yaml)
4. A2A Agent Card generation
5. Tool context setup
6. Testing utilities

Usage (in runtime/server.py):
    from agent import agent, AgentInputSchema
    from tap_wrapper import build_tap_agent, setup_tool_context, generate_agent_card

    # Build production-ready TAP agent with full pipeline
    wrapped_agent = build_tap_agent(agent, AgentInputSchema)

    # Before execution, set up context
    setup_tool_context(gateway_context)

    # Get agent card for discovery endpoint
    agent_card = generate_agent_card(AgentInputSchema, AgentOutputSchema)

Pipeline Architecture:
    SequentialAgent (wrapped_agent):
    ├── Step 1: TapInitialiserAgent (sets up LTM context + personalizes sub-agents)
    ├── Step 2: InputValidator (validates required fields, uses persona snippets)
    └── Step 3: DeveloperAgent (your agent logic)

To add personalization:
    1. Create agent/system_manifest.yaml describing your sub-agent architecture
    2. Add {persona_<agent_name>} placeholders in sub-agent instructions
    3. Gateway will pass sma_interaction_preferences in context
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Type

from google.adk.agents import LlmAgent, BaseAgent
from pydantic import BaseModel

from .config import get_config, AgentConfig
from .mesh_integration import (
    get_mesh_tools,
    setup_tool_context,
    get_oauth_credentials,
    inject_mesh_tools,
)
from .validation import (
    wrap_with_validation,
    wrap_with_full_pipeline,
    get_required_fields,
    create_input_validator,
    CONFIDENCE_THRESHOLD,
)
from .manifest import (
    SystemManifest,
    load_system_manifest,
    load_manifest_dict,
)
from .initialiser import (
    create_tap_initialiser_agent,
    should_use_initialiser,
    INITIALISER_MODEL,
)
from .agent_card import generate_agent_card, get_agent_card, get_agent_card_dict
from .prompts import (
    compose_system_prompt,
    compose_sub_agent_prompt,
    get_all_preference_keys_from_manifest,
    normalize_preference_key,
    get_system_prompt_dict,
    get_context_injection_dict,
    get_prompts,
    PLATFORM_PREAMBLE,
    PLATFORM_FOOTER,
    DEFAULT_PREFERENCES_KEY,
)
from .exceptions import (
    MissingCredentialsError,
    AgentExecutionError,
    ConfigurationError,
    ContextSetupError,
)

logger = logging.getLogger(__name__)


def build_tap_agent(
    developer_agent: BaseAgent,
    input_schema: Type[BaseModel],
    skip_validation: Optional[bool] = None,
    skip_initialiser: Optional[bool] = None,
    skip_mesh_tools: bool = False,
    use_full_pipeline: Optional[bool] = None,
) -> BaseAgent:
    """
    Build a production-ready TAP agent from a developer's agent.

    This is the MAIN ENTRY POINT for TAP agent construction. Called once at
    server startup (server.py:94) to create the wrapped agent that handles
    all incoming requests.

    PIPELINE ARCHITECTURE:
    ======================
    The resulting agent is a SequentialAgent with this structure:

        SequentialAgent (wrapped_agent)
        ├── Step 1: TapInitialiserAgent (if system-manifest.yaml exists)
        │   └── Reads sma_interaction_preferences from Cognee via Gateway context
        │   └── Generates personalized snippets for each sub-agent
        │   └── Stores snippets in session state (e.g., {my_agent_user_preferences})
        │
        ├── Step 2: InputValidator (if input_schema has required fields)
        │   └── Validates required fields are present in user message
        │   └── If missing, calls ask_clarifying_questions() to gather them
        │   └── Uses {input_validator_user_preferences} if personalization enabled
        │
        └── Step 3: DeveloperAgent (your agent)
            └── Your business logic with mesh tools injected
            └── Uses {my_agent_user_preferences} placeholder in instruction

    DECISION FLOW:
    ==============
    1. Inject mesh tools into developer agent (12 universal TAP tools)
    2. Check should_use_initialiser() to determine pipeline type:
       - If system-manifest.yaml exists AND personalization.enabled=true
         AND per_agent_preferences is non-empty → use full pipeline
       - Otherwise → use validation-only pipeline
    3. Wrap agent with appropriate pipeline

    Args:
        developer_agent: The developer's LlmAgent (from agent/agent.py)
        input_schema: Input schema class for validation (from agent/schemas.py)
        skip_validation: Skip InputValidator (default: env TAP_SKIP_VALIDATION)
        skip_initialiser: Skip TapInitialiserAgent (default: env TAP_SKIP_INITIALISER)
        skip_mesh_tools: Skip mesh tools injection (for unit testing)
        use_full_pipeline: Force pipeline type (default: auto-detect from manifest)

    Returns:
        SequentialAgent wrapping the developer agent with TAP integration

    Example:
        # In server.py
        from agent import agent, AgentInputSchema
        from tap_wrapper import build_tap_agent

        wrapped_agent = build_tap_agent(agent, AgentInputSchema)
        # wrapped_agent is now ready for InMemoryRunner
    """
    agent = developer_agent

    # =========================================================================
    # STEP 1: Inject mesh tools (transfer_to_agent, ask_clarifying_questions, etc.)
    # =========================================================================
    # Mesh tools allow agents to communicate with other agents in the TAP mesh.
    # They are injected at the front of the tools list so they take precedence.
    if not skip_mesh_tools and isinstance(agent, LlmAgent):
        agent = _inject_mesh_tools_into_agent(agent)
        logger.info(f"Injected mesh tools into {agent.name}")

    # =========================================================================
    # STEP 2: Determine which pipeline to use
    # =========================================================================
    # Auto-detection checks system-manifest.yaml for:
    #   - personalization.enabled = true
    #   - state_schema.per_agent_preferences has entries
    # If both conditions met → full pipeline with TapInitialiserAgent
    # Otherwise → validation-only pipeline (simpler, lower latency)
    if use_full_pipeline is None:
        use_full_pipeline = should_use_initialiser(skip_initialiser=skip_initialiser)
        logger.info(f"Pipeline auto-detection: use_full_pipeline={use_full_pipeline}")

    # =========================================================================
    # STEP 3: Wrap with appropriate pipeline
    # =========================================================================
    if use_full_pipeline:
        # Full pipeline: TapInitialiserAgent → InputValidator → DeveloperAgent
        # TapInitialiserAgent reads sma_interaction_preferences and sets state variables
        # that are substituted into agent instructions by ADK
        agent = wrap_with_full_pipeline(
            agent,
            input_schema,
            skip_validation=skip_validation,
            skip_initialiser=skip_initialiser,
        )
        logger.info(f"Wrapped {developer_agent.name} with full pipeline (initialiser + validation)")
    else:
        # Validation-only pipeline: InputValidator → DeveloperAgent
        # Simpler and faster, used when personalization is not configured
        agent = wrap_with_validation(agent, input_schema, skip_validation)
        logger.info(f"Wrapped {developer_agent.name} with validation pipeline")

    return agent


def _inject_mesh_tools_into_agent(agent: LlmAgent) -> LlmAgent:
    """
    Create a new LlmAgent with mesh tools injected.

    This creates a copy of the agent with mesh tools prepended to its tool list.

    Args:
        agent: Original LlmAgent

    Returns:
        New LlmAgent with mesh tools
    """
    mesh_tools = get_mesh_tools()
    if not mesh_tools:
        return agent

    # Get existing tools
    existing_tools = agent.tools or []

    # Combine mesh tools with existing tools
    all_tools = [*mesh_tools, *existing_tools]

    # Create new agent with combined tools
    # We need to copy all relevant attributes
    return LlmAgent(
        name=agent.name,
        model=agent.model,
        description=agent.description,
        instruction=agent.instruction,
        tools=all_tools,
        generate_content_config=agent.generate_content_config,
        before_agent_callback=agent.before_agent_callback,
        after_agent_callback=agent.after_agent_callback,
        before_tool_callback=agent.before_tool_callback,
        after_tool_callback=agent.after_tool_callback,
        before_model_callback=agent.before_model_callback,
        after_model_callback=agent.after_model_callback,
        disallow_transfer_to_parent=agent.disallow_transfer_to_parent,
        disallow_transfer_to_peers=agent.disallow_transfer_to_peers,
        output_schema=getattr(agent, 'output_schema', None),
        output_key=getattr(agent, 'output_key', None),
    )


# =============================================================================
# METADATA EXPORTS (for runtime)
# =============================================================================

def get_agent_metadata(
    input_schema: Optional[Type[BaseModel]] = None,
    output_schema: Optional[Type[BaseModel]] = None,
) -> Dict[str, Any]:
    """
    Get agent metadata for TAP registration.

    Args:
        input_schema: Input schema class (optional)
        output_schema: Output schema class (optional)

    Returns:
        Metadata dict with name, description, model, schemas, version
    """
    config = get_config()
    metadata = {
        "name": config.slug,
        "display_name": config.display_name,
        "description": config.description,
        "model": config.model,
        "version": config.version,
    }

    if input_schema:
        metadata["input_schema"] = input_schema.model_json_schema()
    if output_schema:
        metadata["output_schema"] = output_schema.model_json_schema()

    return metadata


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    # Main entry point
    "build_tap_agent",

    # Context setup
    "setup_tool_context",
    "get_oauth_credentials",

    # Agent card
    "generate_agent_card",
    "get_agent_card",
    "get_agent_card_dict",

    # Metadata
    "get_agent_metadata",

    # Config
    "get_config",
    "AgentConfig",

    # Mesh tools (for advanced usage)
    "get_mesh_tools",
    "inject_mesh_tools",

    # Validation (for advanced usage)
    "wrap_with_validation",
    "wrap_with_full_pipeline",
    "get_required_fields",
    "create_input_validator",
    "CONFIDENCE_THRESHOLD",

    # Manifest (for advanced usage)
    "SystemManifest",
    "load_system_manifest",
    "load_manifest_dict",

    # Initialiser (for advanced usage)
    "create_tap_initialiser_agent",
    "should_use_initialiser",
    "INITIALISER_MODEL",

    # Prompts composition
    "compose_system_prompt",
    "compose_sub_agent_prompt",
    "get_all_preference_keys_from_manifest",
    "normalize_preference_key",
    "get_system_prompt_dict",
    "get_context_injection_dict",
    "get_prompts",
    "PLATFORM_PREAMBLE",
    "PLATFORM_FOOTER",
    "DEFAULT_PREFERENCES_KEY",

    # Exceptions
    "MissingCredentialsError",
    "AgentExecutionError",
    "ConfigurationError",
    "ContextSetupError",
]
