"""
TAP Wrapper - TapInitialiserAgent

Personalizes agent behavior based on user preferences from Cognee knowledge graph.
This is the FIRST agent in the TAP pipeline - it runs before InputValidator and
the developer's agent to set up personalized context.

=============================================================================
WHEN DOES THIS RUN?
=============================================================================

TapInitialiserAgent is automatically included in the pipeline when:
1. agent/system-manifest.yaml exists
2. personalization.enabled = true (in manifest)
3. state_schema.per_agent_preferences has at least one entry

The decision is made by should_use_initialiser() which is called by
build_tap_agent() in tap_wrapper/__init__.py during server startup.

=============================================================================
DATA FLOW
=============================================================================

    Gateway                          server.py                 TapInitialiserAgent
    ───────                          ─────────                 ───────────────────
    │                                    │                            │
    │  context.sma_interaction_         │                            │
    │  preferences (List[Dict])────────>│                            │
    │  [{"content":"..."},...]          │                            │
    │                                    │  Converts to text:        │
    │                                    │  "- preference 1           │
    │                                    │   - preference 2"         │
    │                                    │                            │
    │                                    │  state["sma_interaction_  │
    │                                    │  preferences"] = text ───>│
    │                                    │                            │
    │                                    │                  Reads manifest + preferences
    │                                    │                  Generates per-agent snippets
    │                                    │                            │
    │                                    │        state["my_agent_user_preferences"]──> Downstream
    │                                    │                            │                  Agents
    │                                    │                            │
    │                                    │              ADK substitutes {my_agent_user_preferences}

=============================================================================
PIPELINE ARCHITECTURE
=============================================================================

    SequentialAgent (wrapped_agent created by build_tap_agent)
    │
    ├── Step 1: TapInitialiserAgent (THIS MODULE)
    │   └── Reads sma_interaction_preferences from Gateway context
    │   └── Reads system-manifest.yaml to understand agent architecture
    │   └── Generates personalized snippets for each sub-agent
    │   └── Stores snippets in session state via after_agent_callback
    │   └── Example: state["my_agent_user_preferences"] = "User prefers concise answers"
    │
    ├── Step 2: InputValidator
    │   └── Validates required fields from AgentInputSchema
    │   └── Uses {input_validator_user_preferences} in its prompt
    │
    └── Step 3: DeveloperAgent
        └── Your business logic
        └── Uses {my_agent_user_preferences} in its instruction

=============================================================================
KEY FILES
=============================================================================

- agent/system-manifest.yaml   → Defines agent architecture and preference keys
- tap_wrapper/initialiser.py   → THIS FILE - TapInitialiserAgent implementation
- tap_wrapper/validation.py    → wrap_with_full_pipeline() that chains agents
- tap_wrapper/__init__.py      → build_tap_agent() entry point

=============================================================================
NAMING CONVENTION
=============================================================================

State keys follow the pattern: {agent_name}_user_preferences
Examples:
    - my_agent_user_preferences (main agent)
    - input_validator_user_preferences (validation agent)
    - researcher_user_preferences (sub-agent)

These keys are defined in system-manifest.yaml under state_schema.per_agent_preferences.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.genai import types
from pydantic import BaseModel, Field

from .manifest import SystemManifest, load_system_manifest

logger = logging.getLogger(__name__)

# Model for initialiser - use fast model for quick personalization
INITIALISER_MODEL = os.environ.get("TAP_INITIALISER_MODEL", "gemini-3-flash-preview")


# =============================================================================
# OUTPUT SCHEMA
# =============================================================================

class PersonalizationOutput(BaseModel):
    """Output schema for TapInitialiserAgent."""

    snippets: Dict[str, str] = Field(
        ...,
        description="Map of state_key -> personalized instruction snippet"
    )
    ltm_summary: str = Field(
        default="",
        description="Summary of relevant long-term memory context"
    )
    reasoning: str = Field(
        ...,
        description="Brief explanation of personalization decisions"
    )


# =============================================================================
# INSTRUCTION GENERATION
# =============================================================================

def create_initialiser_instruction(manifest: SystemManifest) -> str:
    """
    Generate TapInitialiserAgent instruction from manifest.

    Creates a detailed prompt that:
    1. Explains the agent system architecture
    2. Lists each agent's preference configuration from state_schema
    3. Instructs the LLM to generate personalized snippets
    4. Handles LTM context summarization

    Args:
        manifest: Loaded and validated system manifest

    Returns:
        Complete instruction prompt for TapInitialiserAgent
    """
    system_info = manifest.system
    personalization = manifest.personalization
    per_agent_prefs = manifest.state_schema.per_agent_preferences

    # Build agent preference sections from state_schema
    agent_sections = []
    state_keys = []

    for state_key, pref in per_agent_prefs.items():
        state_keys.append(state_key)
        agent_name = state_key.replace("_user_preferences", "").replace("_", " ").title()

        agent_sections.append(f"""
### {agent_name} (state_key: `{state_key}`)

**Domain:** {pref.domain or "Not specified"}

**Description:** {pref.description.strip() if pref.description else "No description provided."}

**Example Feedback:** {pref.example_feedback.strip() if pref.example_feedback else "No examples."}

**What to Extract:** {pref.wrapper_guidance.strip() if pref.wrapper_guidance else "Use your judgment."}
""")

    agents_content = "".join(agent_sections) if agent_sections else "No agents defined for personalization."

    # Generate example output - show ALL keys so LLM knows to include them all
    example_snippets = {}
    for i, sk in enumerate(state_keys):
        # Vary the examples slightly to show LLM should customize per agent
        examples = [
            "Use a friendly, conversational tone. Keep explanations concise.",
            "Focus on technical accuracy. Provide detailed explanations when needed.",
            "Be concise and action-oriented. Skip excessive pleasantries.",
        ]
        example_snippets[sk] = examples[i % len(examples)]

    return f'''You are the TAP Initialiser Agent. Your job is to set up personalized context for all downstream agents.

You run FIRST in the pipeline, before any other agents (including InputValidator).
Your output directly affects how all downstream agents behave.

## System Information

**Name:** {system_info.name or "Unknown Agent"}
**Purpose:** {system_info.purpose.strip() if system_info.purpose else "Not specified."}

## Your Tasks

### 1. Analyze User Preferences

Below are the user's interaction preferences from Cognee (may be empty if no feedback recorded):

**User Preferences:**
{{{personalization.user_preferences_key}?}}

**Long-Term Memory Context:**
{{ltm?}}

**Delegation Context:**
{{delegation_context?}}

### 2. Generate Personalization Snippets

For each agent below, generate a **2-4 sentence instruction snippet** that:
- Extracts relevant preferences from the User Preferences section above
- Provides actionable guidance for that specific agent
- Is specific, not generic (avoid "be helpful" - give concrete instructions)

### 3. Summarize LTM Context

If the Long-Term Memory Context section above has entries, extract key facts that may be useful for downstream agents.
Store a summary in the `ltm_summary` field.

## Agents to Personalize

{agents_content}

## Output Format

Return a JSON object with:
- `snippets`: Dictionary mapping each state_key to its personalized snippet
- `ltm_summary`: Brief summary of relevant LTM context (empty string if none)
- `reasoning`: Brief explanation of your personalization decisions

```json
{{
  "snippets": {json.dumps(example_snippets, indent=4)},
  "ltm_summary": "User previously worked on healthcare projects. Prefers detailed explanations.",
  "reasoning": "User indicated preference for technical accuracy and friendly tone. Applied to input validator and main agent."
}}
```

## Required State Keys (MUST include all of these)

{chr(10).join(f"- `{sk}`" for sk in state_keys) if state_keys else "- No keys defined"}

## Important Rules

1. **Generate ALL state_keys listed above** - Your output MUST include a snippet for every key in the "Required State Keys" section
2. **Use the EXACT state_key names** - Copy/paste from the list above. Do not invent new keys or modify the names.
3. **Keep snippets actionable** - 2-4 sentences of concrete guidance
4. **Handle missing preferences** - If User Preferences section above is empty, use professional defaults
5. **Be specific** - "Use friendly tone" is better than "be nice"
6. **Parse the bullet points** - User preferences is a newline-separated list of preference statements (each line starts with -)
7. **Consider domain** - Each agent's domain tells you what kind of preferences matter
'''


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _extract_json_from_codeblock(text: str) -> str:
    """
    Extract JSON from a text that may be wrapped in code blocks.

    Handles various LLM output patterns:
    - ```json\n{...}\n```
    - ```\n{...}\n```
    - Raw JSON (no code block)
    - Malformed code blocks (missing closing)

    Args:
        text: Raw LLM output text

    Returns:
        Extracted JSON string (may be empty if extraction fails)
    """
    text = text.strip()

    # Try to extract from ```json ... ``` first
    json_block_match = re.search(r"```json\s*([\s\S]*?)```", text)
    if json_block_match:
        return json_block_match.group(1).strip()

    # Try generic ``` ... ```
    generic_block_match = re.search(r"```\s*([\s\S]*?)```", text)
    if generic_block_match:
        return generic_block_match.group(1).strip()

    # Check if it starts with ``` but has no closing (malformed)
    if text.startswith("```"):
        # Try to extract everything after the opening marker
        lines = text.split("\n", 1)
        if len(lines) > 1:
            # Skip the ``` line, take the rest
            remaining = lines[1]
            # Remove any trailing ``` if present at the end
            if remaining.rstrip().endswith("```"):
                remaining = remaining.rstrip()[:-3].rstrip()
            return remaining.strip()

    # No code block detected, return as-is (might already be raw JSON)
    return text


# =============================================================================
# AFTER AGENT CALLBACK
# =============================================================================

async def distribute_snippets_to_state(
    callback_context: CallbackContext,
) -> None:
    """
    After TapInitialiserAgent completes, distribute personalization
    snippets to individual state keys for each agent.

    This callback:
    1. Extracts the JSON output from personalization_result
    2. Parses snippets dictionary
    3. Sets each snippet to its corresponding state key (e.g., mechanic_user_preferences)
    4. Sets LTM summary for downstream agents
    5. Sets metadata flags for debugging

    On failure, applies fallback snippets to all agents.

    Args:
        callback_context: ADK callback context with state access
    """
    try:
        # Get the raw output from state
        result = callback_context.state.get("personalization_result", "")

        if not result or not str(result).strip():
            logger.warning("TapInitialiserAgent produced no output")
            await _apply_fallback_snippets(callback_context, "No output from TapInitialiserAgent")
            return

        # Ensure result is a string
        result = str(result)

        # Handle code block wrapping (LLM sometimes wraps in ```json)
        # Use more robust extraction that handles edge cases
        result = _extract_json_from_codeblock(result)

        if not result.strip():
            logger.warning("TapInitialiserAgent output is empty after code block extraction")
            await _apply_fallback_snippets(callback_context, "Empty output after code block extraction")
            return

        # Parse JSON output
        parsed = json.loads(result.strip())
        snippets = parsed.get("snippets", {})
        ltm_summary = parsed.get("ltm_summary", "")
        reasoning = parsed.get("reasoning", "")

        if not snippets:
            logger.warning("TapInitialiserAgent returned empty snippets")
            await _apply_fallback_snippets(callback_context)
            return

        # Load manifest to get expected preference keys
        manifest = load_system_manifest()
        expected_keys = set(manifest.get_preference_keys())
        fallback = manifest.personalization.fallback_snippet

        # Track which keys were set vs missing
        keys_set = set()
        unexpected_keys = []

        # Distribute each snippet to its state key (with validation)
        for state_key, snippet in snippets.items():
            if expected_keys and state_key not in expected_keys:
                # LLM hallucinated a key that doesn't exist in manifest
                unexpected_keys.append(state_key)
                logger.warning(
                    f"TapInitialiserAgent returned unexpected key '{state_key}' "
                    f"(expected: {sorted(expected_keys)}). Ignoring."
                )
                continue

            # Validate snippet value is a non-empty string
            if not isinstance(snippet, str):
                logger.warning(
                    f"Snippet for '{state_key}' is not a string (got {type(snippet).__name__}). "
                    f"Using fallback."
                )
                callback_context.state[state_key] = fallback
                keys_set.add(state_key)
                continue

            if not snippet.strip():
                logger.warning(
                    f"Snippet for '{state_key}' is empty. Using fallback."
                )
                callback_context.state[state_key] = fallback
                keys_set.add(state_key)
                continue

            callback_context.state[state_key] = snippet
            keys_set.add(state_key)
            preview = snippet[:50] + "..." if len(snippet) > 50 else snippet
            logger.debug(f"Set {state_key} = {preview}")

        # Apply fallback for any expected keys not provided by LLM
        missing_keys = expected_keys - keys_set
        if missing_keys:
            logger.warning(
                f"TapInitialiserAgent did not return snippets for: {sorted(missing_keys)}. "
                f"Applying fallback."
            )
            for missing_key in missing_keys:
                callback_context.state[missing_key] = fallback
                logger.debug(f"Set {missing_key} = (fallback)")

        # Log summary of unexpected keys if any
        if unexpected_keys:
            logger.warning(
                f"LLM returned {len(unexpected_keys)} unexpected keys (hallucination): {unexpected_keys}"
            )

        # Set LTM summary for downstream agents to use
        if ltm_summary and isinstance(ltm_summary, str) and ltm_summary.strip():
            callback_context.state["ltm_summary"] = ltm_summary
            preview = ltm_summary[:100] + "..." if len(ltm_summary) > 100 else ltm_summary
            logger.debug(f"Set ltm_summary = {preview}")

        # Store metadata for debugging
        callback_context.state["tap_init_complete"] = True
        callback_context.state["tap_init_reasoning"] = reasoning
        callback_context.state["tap_init_snippet_count"] = len(keys_set)
        callback_context.state["tap_init_has_ltm"] = bool(ltm_summary)
        callback_context.state["tap_init_missing_keys"] = list(missing_keys)
        callback_context.state["tap_init_unexpected_keys"] = unexpected_keys

        logger.info(
            f"TapInitialiserAgent distributed {len(keys_set)} preference snippets: {sorted(keys_set)}"
            + (f" (missing: {sorted(missing_keys)})" if missing_keys else "")
            + (f" (unexpected: {unexpected_keys})" if unexpected_keys else "")
        )

    except json.JSONDecodeError as e:
        logger.error(f"TapInitialiserAgent output is not valid JSON: {e}")
        await _apply_fallback_snippets(callback_context, f"Invalid JSON output: {e}")

    except Exception as e:
        logger.error(f"TapInitialiserAgent failed to distribute snippets: {e}", exc_info=True)
        await _apply_fallback_snippets(callback_context, f"Snippet distribution failed: {e}")


async def _apply_fallback_snippets(
    callback_context: CallbackContext,
    error_message: str = "Personalization failed, using fallback",
) -> None:
    """
    Apply fallback snippets when personalization fails.

    Loads manifest to get fallback text and agent list,
    then sets fallback snippet to all state keys.

    IMPORTANT: This function is resilient - if manifest loading fails,
    it uses a hardcoded fallback to ensure state is always set.

    Args:
        callback_context: ADK callback context with state access
        error_message: Error message to store in state for debugging
    """
    # Default fallback in case manifest loading also fails
    DEFAULT_FALLBACK = "Proceed with default professional behavior."
    fallback = DEFAULT_FALLBACK
    preference_keys = []

    try:
        manifest = load_system_manifest()
        fallback = manifest.personalization.fallback_snippet or DEFAULT_FALLBACK

        # Get all preference keys using the same method as the main callback
        # This covers: state_schema, personalization.preference_keys, and legacy sub_agents
        preference_keys = manifest.get_preference_keys()
    except Exception as e:
        # Even if manifest loading fails, we continue with defaults
        logger.error(f"Failed to load manifest in fallback handler: {e}")
        # preference_keys stays empty - we can't set anything without knowing the keys
        # But we still need to mark the state properly

    # Apply fallback to all known preference keys
    for state_key in preference_keys:
        callback_context.state[state_key] = fallback

    # Always set metadata, even if we couldn't load preference keys
    callback_context.state["tap_init_complete"] = False
    callback_context.state["tap_init_error"] = error_message

    if preference_keys:
        logger.info(f"Applied fallback snippet to {len(preference_keys)} agents: {preference_keys}")
    else:
        logger.warning("Could not apply fallback - no preference keys known")


# =============================================================================
# AGENT FACTORY
# =============================================================================

def create_tap_initialiser_agent(
    manifest: Optional[SystemManifest] = None,
    model: Optional[str] = None,
) -> Optional[LlmAgent]:
    """
    Create the TapInitialiserAgent from system manifest.

    This factory function is called by wrap_with_full_pipeline() in validation.py
    when building the TAP agent pipeline. It creates an LlmAgent that:

    1. Receives sma_interaction_preferences in session state (set by server.py from Gateway context)
    2. Reads system-manifest.yaml to understand the agent architecture
    3. Generates personalized instruction snippets for each sub-agent
    4. Stores snippets in session state via after_agent_callback (distribute_snippets_to_state)

    The agent uses JSON output mode (response_mime_type="application/json") for
    structured parsing, and low temperature (0.3) for consistent results.

    WHEN THIS RETURNS None:
    - No manifest provided and none found in agent/ directory
    - personalization.enabled = false in manifest
    - state_schema.per_agent_preferences is empty

    When None is returned, the pipeline falls back to validation-only mode
    (no personalization).

    Args:
        manifest: SystemManifest instance (loads from agent/system-manifest.yaml if not provided)
        model: LLM model to use (defaults to TAP_INITIALISER_MODEL env var or gemini-3-flash-preview)

    Returns:
        Configured LlmAgent for personalization, or None if personalization not configured

    Example:
        # Usually called internally by wrap_with_full_pipeline()
        initialiser = create_tap_initialiser_agent()
        if initialiser:
            # Add to pipeline
            pipeline_agents.insert(0, initialiser)
    """
    if manifest is None:
        manifest = load_system_manifest()

    if model is None:
        model = INITIALISER_MODEL

    # Check if personalization is enabled
    if not manifest.personalization.enabled:
        logger.info("Personalization disabled in manifest, skipping TapInitialiserAgent")
        return None

    # Check if any agents have preference configurations
    # Use get_preference_keys() to cover all sources (state_schema, personalization, legacy)
    preference_keys = manifest.get_preference_keys()

    if not preference_keys:
        logger.info("No preference keys defined, skipping TapInitialiserAgent")
        return None

    # Generate instruction from manifest
    instruction = create_initialiser_instruction(manifest)

    logger.info(
        f"Creating TapInitialiserAgent for {len(preference_keys)} agents: {preference_keys}"
    )

    return LlmAgent(
        name="TapInitialiserAgent",
        model=model,
        description=(
            "Initializes personalized context for all downstream agents based on "
            "user preferences from Cognee. Sets *_user_preferences state variables."
        ),
        instruction=instruction,
        tools=[],  # Pure reasoning, no tools needed
        output_key="personalization_result",
        generate_content_config=types.GenerateContentConfig(
            temperature=0.3,  # Low temp for consistent output
            response_mime_type="application/json",
        ),
        after_agent_callback=distribute_snippets_to_state,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


def should_use_initialiser(
    manifest: Optional[SystemManifest] = None,
    skip_initialiser: Optional[bool] = None,
) -> bool:
    """
    Check if TapInitialiserAgent should be used in the pipeline.

    This is the KEY DECISION FUNCTION called by build_tap_agent() to determine
    which pipeline to use:
    - Returns True  → wrap_with_full_pipeline() (includes TapInitialiserAgent)
    - Returns False → wrap_with_validation() (simpler, no personalization)

    DECISION LOGIC (all conditions must be true):
    =============================================
    1. TAP_SKIP_INITIALISER env var is NOT "true"
    2. skip_initialiser parameter is not True
    3. system-manifest.yaml exists in agent/ directory
    4. personalization.enabled = true in manifest
    5. state_schema.per_agent_preferences has at least one entry

    If ANY condition fails, returns False and the simpler pipeline is used.

    CALL CHAIN:
    ===========
    server.py:94
        └── build_tap_agent()
            └── should_use_initialiser() ← THIS FUNCTION
                └── Returns True/False
                    └── True:  wrap_with_full_pipeline()
                    └── False: wrap_with_validation()

    Args:
        manifest: SystemManifest instance (auto-loads from agent/system-manifest.yaml if None)
        skip_initialiser: Force skip (overrides env var, useful for testing)

    Returns:
        True if TapInitialiserAgent should be included in pipeline, False otherwise

    Example:
        # Auto-detection in build_tap_agent
        use_full_pipeline = should_use_initialiser()

        # Force skip for testing
        use_full_pipeline = should_use_initialiser(skip_initialiser=True)  # Always False
    """
    # =========================================================================
    # CHECK 1: Explicit skip flag (env var or parameter)
    # =========================================================================
    if skip_initialiser is None:
        skip_initialiser = os.environ.get("TAP_SKIP_INITIALISER", "").lower() == "true"

    if skip_initialiser:
        logger.debug("TapInitialiserAgent skipped via flag")
        return False

    # =========================================================================
    # CHECK 2: Load and validate manifest
    # =========================================================================
    if manifest is None:
        manifest = load_system_manifest()

    # =========================================================================
    # CHECK 3: Personalization must be enabled in manifest
    # =========================================================================
    if not manifest.personalization.enabled:
        logger.debug("TapInitialiserAgent skipped: personalization.enabled=false")
        return False

    # =========================================================================
    # CHECK 4: At least one agent must have preference configuration
    # =========================================================================
    # Use get_preference_keys() for consistency with other code paths
    # This covers: state_schema, personalization.preference_keys, and legacy sub_agents
    preference_keys = manifest.get_preference_keys()
    has_preferences = len(preference_keys) > 0
    if not has_preferences:
        logger.debug("TapInitialiserAgent skipped: no preference keys defined")
    else:
        logger.debug(f"TapInitialiserAgent enabled: {len(preference_keys)} preference keys found")
    return has_preferences


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Main factory
    "create_tap_initialiser_agent",
    # Helpers
    "should_use_initialiser",
    "create_initialiser_instruction",
    "distribute_snippets_to_state",
    # Models
    "PersonalizationOutput",
    # Constants
    "INITIALISER_MODEL",
]
