"""
TAP Wrapper - Automatic Input Validation

Platform-level input validation for ALL SMAs.
This is automatically applied by the TAP runtime - developers don't touch this.

The wrapper:
1. Detects required fields from the developer's input schema
2. Creates an InputValidator LlmAgent that checks if all required fields are present
3. If fields are missing → calls ask_clarifying_questions() to gather them
4. If all fields are present → proceeds to the developer's agent
5. Uses a 2-step SequentialAgent: [InputValidator, DeveloperAgent]
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING, get_type_hints

if TYPE_CHECKING:
    # Note: TapInitialiserAgent is created by create_tap_initialiser_agent(),
    # not a class. This import is for type hints only.
    from .manifest import SystemManifest

from google.adk.agents import LlmAgent, SequentialAgent, BaseAgent
from google.genai import types
from pydantic import BaseModel, Field, create_model

logger = logging.getLogger(__name__)

# Model for validation - use fast model for quick validation
VALIDATION_MODEL = os.environ.get("TAP_VALIDATION_MODEL", "gemini-3-flash-preview")

# Platform fields to skip during required field detection
PLATFORM_FIELDS = {"session_id", "trace_id", "client_id", "oauth_credentials"}

# Minimum confidence threshold for proceeding without clarification
# Configurable via TAP_CONFIDENCE_THRESHOLD environment variable
CONFIDENCE_THRESHOLD = float(os.environ.get("TAP_CONFIDENCE_THRESHOLD", "0.7"))

# Map ui_widget to question type for ask_clarifying_questions
UI_WIDGET_TO_QUESTION_TYPE = {
    "text": "text",
    "textarea": "text",
    "select": "choice",
    "radio": "choice",
    "checkbox": "boolean",
    "checkbox_group": "multi_choice",
    "file": "file",
    "number": "text",  # No native number in ask_clarifying_questions
    "date": "text",
    "url": "text",
    "email": "text",
}


def get_required_fields(schema_class: Type[BaseModel]) -> List[Dict[str, Any]]:
    """
    Extract required fields from a Pydantic model with full metadata.

    A field is considered required if:
    - It's in the schema's "required" list, OR
    - Pydantic's is_required() returns True

    Platform fields (session_id, trace_id, etc.) are automatically excluded.

    Args:
        schema_class: The Pydantic model class to introspect

    Returns:
        List of dicts with:
        - name: field name
        - description: field description
        - prompt_question: question to ask user (if defined in json_schema_extra)
        - type: JSON schema type (string, integer, etc.)
        - python_type: Original Python type annotation
        - ui_widget: UI widget hint from json_schema_extra
        - options: Options for select/choice fields
    """
    schema = schema_class.model_json_schema()
    properties = schema.get("properties", {})
    required_list = set(schema.get("required", []))

    # Get field info from the model itself for better default detection
    model_fields = getattr(schema_class, "model_fields", {})

    # Get type hints for Python type preservation
    try:
        type_hints = get_type_hints(schema_class)
    except Exception as e:
        logger.warning(f"Could not get type hints for {schema_class.__name__}: {e}")
        type_hints = {}

    fields = []
    for name, prop in properties.items():
        # Skip platform-injected fields
        if name in PLATFORM_FIELDS:
            continue

        # Skip fields marked as platform_provided
        if prop.get("platform_provided"):
            continue

        # Determine if field is required
        # Primary: Check JSON schema "required" list
        is_required = name in required_list

        # Secondary: Check Pydantic's is_required() for fields with ... default
        if not is_required and name in model_fields:
            field_info = model_fields[name]
            try:
                is_required = field_info.is_required()
            except Exception:
                pass

        if is_required:
            fields.append({
                "name": name,
                "description": prop.get("description", f"The {name} field"),
                "prompt_question": prop.get("prompt_question", f"What is the {name}?"),
                "type": prop.get("type", "string"),
                "python_type": type_hints.get(name, str),
                "ui_widget": prop.get("ui_widget", "text"),
                "options": prop.get("prompt_options", []),
            })

    return fields


def generate_validator_prompt(required_fields: List[Dict[str, Any]], agent_name: str) -> str:
    """
    Generate the InputValidator prompt based on required fields.

    The prompt instructs the LLM to:
    - Check if all required fields are present in the user's message or history
    - Extract values from context if clearly stated
    - Ask clarifying questions if any field is missing or ambiguous
    - Use ask_clarifying_questions for text answers, request_input for structured data
    - Enforce 0.7 confidence threshold before proceeding

    Args:
        required_fields: List of required field definitions
        agent_name: Name of the developer's agent (for context)

    Returns:
        Complete instruction prompt for the InputValidator
    """
    field_descriptions = "\n".join([
        f"- **{f['name']}** ({f.get('ui_widget', 'text')}): {f['description']}"
        for f in required_fields
    ])

    field_names = ", ".join([f["name"] for f in required_fields])

    # Build question schema for ask_clarifying_questions tool
    clarifying_questions_schema = json.dumps([
        {
            "id": f["name"],
            "question": f["prompt_question"],
            "type": UI_WIDGET_TO_QUESTION_TYPE.get(f.get("ui_widget", "text"), "text"),
            "required": True,
            **({"options": f["options"]} if f.get("options") else {}),
        }
        for f in required_fields
    ], indent=2)

    # Build field schema for request_input tool
    request_input_schema = json.dumps([
        {
            "name": f["name"],
            "label": f["prompt_question"].rstrip("?"),
            "type": f.get("ui_widget", "text"),
            "required": True,
            "description": f["description"],
            **({"options": [{"value": o, "label": o} for o in f["options"]]} if f.get("options") else {}),
        }
        for f in required_fields
    ], indent=2)

    return f"""You are the Input Validator for {agent_name}.

Your job is to ensure we have all required information before the main agent begins work.

## History and Feedback Based User Preferences

**IMPORTANT:** This section contains dynamically-loaded user preferences based on your past behavior
and feedback from previous sessions. The TapInitialiserAgent automatically populates this section.

**What to do with this feedback:**
- If feedback says "stop doing X" → Do not do X, even if your default behavior would
- If feedback says "always do Y" → Prioritize Y over conflicting guidance
- If no feedback is provided → Use your default professional judgment

**Current User Preferences:**
{{input_validator_user_preferences?}}

## Required Fields

{field_descriptions}

---

## Step 1: Check Conversation History (Multi-Turn Handling)

**IMPORTANT**: Before asking new questions, check if answers already exist in the conversation history.

Look for:
1. Previous questions you (or another agent) asked
2. User's responses to those questions
3. Values mentioned anywhere in the conversation

If the history contains answers to required fields, extract them. Do NOT re-ask questions that have already been answered.

---

## Step 2: Extract Values and Assess Confidence

For each required field ({field_names}), determine:
1. Is the value clearly stated? (confidence 0.9+)
2. Can it be reasonably inferred from context? (confidence 0.7-0.9)
3. Is it ambiguous or missing? (confidence < 0.7)

**Confidence Scale:**
- 0.9+ : Value explicitly stated by user
- 0.7-0.9 : Value can be confidently inferred from context
- 0.5-0.7 : Value is ambiguous - needs clarification
- Below 0.5 : Value is missing - must ask

**CRITICAL**: If your overall confidence is below {CONFIDENCE_THRESHOLD}, you MUST ask for clarification before proceeding.

---

## Step 3: Choosing How to Ask Questions

You have TWO tools for gathering information. Choose based on the data type:

### ask_clarifying_questions
Use for: Simple text answers, yes/no questions, open-ended responses
- "What topic would you like to research?"
- "Do you want a detailed or summary report?"
- When user just needs to type a text answer

Example format:
```json
{clarifying_questions_schema}
```

### request_input
Use for: Structured data with specific field types and better UX
- URLs (provides key-value pairs like {{"google_doc_url": "https://..."}})
- Selections from predefined options (dropdowns, radio buttons)
- Numbers with validation (budget, quantity)
- File uploads
- Multiple related fields at once

Example format:
```json
{request_input_schema}
```

**The `request_input` tool creates a modal form** with labeled fields and common input patterns (file pickers, dropdowns, etc.). This provides better UX for structured data collection.

---

## Step 4: Output

**When all fields are collected with confidence >= {CONFIDENCE_THRESHOLD}:**

Output a ValidatedInputSchema with:
- All extracted field values
- confidence: Your overall confidence (0.0-1.0)
- source: 'user_input', 'context', or 'clarified'

Your output becomes the input to the main agent. Format it clearly so the main agent understands what was requested.

---

## Handling Edge Cases

### Off-Topic or Unclear Requests
If the user's request seems unrelated to the fields you need:
1. First, ask for clarification using ask_clarifying_questions
2. If still unclear after one round, proceed with:
   - Extract what you can
   - confidence: 0.5 or lower
   - source: "unclear"

Never refuse to output. The main agent will decide how to handle unclear input.

### Vague Messages Like "help me" or "do something"
These require clarification. Use ask_clarifying_questions to determine:
- What specific task the user wants
- Any other required field values

---

## Summary

1. Check history for existing answers
2. Extract values and assess confidence per field
3. If any field has confidence < {CONFIDENCE_THRESHOLD}, ask questions
4. Choose ask_clarifying_questions (text) or request_input (structured data)
5. Once confidence >= {CONFIDENCE_THRESHOLD} for all fields, output ValidatedInputSchema
"""


def create_validated_input_schema(required_fields: List[Dict[str, Any]]) -> Type[BaseModel]:
    """
    Dynamically create the ValidatedInputSchema based on required fields.

    This creates a Pydantic model at runtime with:
    - All required fields with their ORIGINAL Python types preserved
    - confidence: float score (0-1) for extraction confidence
    - source: string indicating where values came from

    Args:
        required_fields: List of required field definitions (includes python_type from get_required_fields)

    Returns:
        Dynamically created Pydantic model class
    """
    field_definitions = {}
    for f in required_fields:
        # Use the original Python type instead of converting everything to str
        python_type = f.get("python_type", str)
        field_definitions[f["name"]] = (python_type, Field(..., description=f["description"]))

    # Add standard validation metadata fields
    field_definitions["confidence"] = (
        float,
        Field(default=1.0, ge=0.0, le=1.0, description="Confidence in extracted values (0.0-1.0)")
    )
    field_definitions["source"] = (
        str,
        Field(default="user_input", description="Where values came from: user_input, context, clarified, or unclear")
    )

    return create_model("ValidatedInputSchema", **field_definitions)


def get_mesh_tools() -> List:
    """
    Get mesh tools for input validation from tap_core.

    Returns both tools:
    - ask_clarifying_questions: For simple text-based Q&A
    - request_input: For structured data collection with modal forms

    Returns empty list if tap_core is not available (local development without TAP).

    Returns:
        List of tool functions
    """
    tools = []
    try:
        from tap_core.tools.mesh_tools import ask_clarifying_questions, request_input
        tools.append(ask_clarifying_questions)
        tools.append(request_input)
        logger.debug("Loaded both validation tools: ask_clarifying_questions, request_input")
    except ImportError as e:
        logger.warning(f"tap_core not available - validation will proceed without question tools: {e}")
    return tools


def create_input_validator(
    required_fields: List[Dict[str, Any]],
    agent_name: str,
    model: str = None,
) -> LlmAgent:
    """
    Create an InputValidator agent for the given required fields.

    The InputValidator:
    - Examines user input and context (including conversation history)
    - Checks if all required fields are present with sufficient confidence
    - Uses ask_clarifying_questions for text answers or request_input for structured data
    - Enforces 0.7 confidence threshold before proceeding
    - Outputs ValidatedInputSchema when all fields are collected

    Args:
        required_fields: List of required field definitions
        agent_name: Name of the developer's agent
        model: Model to use (defaults to VALIDATION_MODEL)

    Returns:
        Configured LlmAgent for input validation
    """
    if model is None:
        model = VALIDATION_MODEL

    prompt = generate_validator_prompt(required_fields, agent_name)
    output_schema = create_validated_input_schema(required_fields)

    # Get both tools: ask_clarifying_questions and request_input
    tools = get_mesh_tools()

    return LlmAgent(
        name="InputValidator",
        model=model,
        description=(
            "Validates that all required input fields are present before the main agent begins work. "
            "Checks conversation history for existing answers. "
            "Uses ask_clarifying_questions for text or request_input for structured data. "
            "Enforces 0.7 confidence threshold."
        ),
        instruction=prompt,
        tools=tools,
        output_schema=output_schema,
        output_key="validated_input",
        generate_content_config=types.GenerateContentConfig(
            temperature=0.3,  # Low temp for consistent judgment
        ),
        # NOTE: Removed disallow_transfer_to_parent and disallow_transfer_to_peers
        # to allow the validator to handle off-topic requests gracefully
    )


def wrap_with_validation(
    developer_agent: BaseAgent,
    input_schema: Type[BaseModel],
    skip_validation: bool = None,
) -> BaseAgent:
    """
    Wrap a developer's agent with automatic input validation.

    This is called by the TAP runtime (server.py) to wrap any developer agent
    with an InputValidator that ensures all required fields are present before
    the main agent runs.

    The wrapper creates a SequentialAgent with:
    1. InputValidator - validates/collects required fields
    2. DeveloperAgent - the original agent

    Args:
        developer_agent: The developer's root_agent
        input_schema: The developer's AgentInputSchema class
        skip_validation: Override for TAP_SKIP_VALIDATION env var

    Returns:
        SequentialAgent with [InputValidator, developer_agent], or
        the original agent if:
        - validation is skipped (env var or parameter)
        - no required fields detected in schema
    """
    # Check if validation should be skipped
    if skip_validation is None:
        skip_validation = os.environ.get("TAP_SKIP_VALIDATION", "").lower() == "true"

    if skip_validation:
        logger.info("Input validation skipped (TAP_SKIP_VALIDATION=true)")
        return developer_agent

    # Detect required fields from schema
    required_fields = get_required_fields(input_schema)

    if not required_fields:
        logger.info("No required fields detected in schema, skipping validation wrapper")
        return developer_agent

    logger.info(
        f"Wrapping agent with validation for {len(required_fields)} required fields: "
        f"{[f['name'] for f in required_fields]}"
    )

    # Create the InputValidator
    input_validator = create_input_validator(
        required_fields=required_fields,
        agent_name=developer_agent.name,
    )

    # Wrap in SequentialAgent
    return SequentialAgent(
        name=f"{developer_agent.name}WithValidation",
        description=f"Input validation wrapper for {developer_agent.name}. Validates required fields before executing the main agent.",
        sub_agents=[
            input_validator,
            developer_agent,
        ],
    )


# =============================================================================
# FULL PIPELINE WRAPPER (Validation + Personalization)
# =============================================================================

def wrap_with_full_pipeline(
    developer_agent: BaseAgent,
    input_schema: Type[BaseModel],
    skip_validation: bool = None,
    skip_initialiser: bool = None,
) -> BaseAgent:
    """
    Wrap developer agent with full TAP pipeline including personalization.

    This is the MAIN PIPELINE FACTORY called by build_tap_agent() when
    personalization is enabled (detected by should_use_initialiser()).

    ==========================================================================
    PIPELINE ARCHITECTURE
    ==========================================================================

        SequentialAgent (returned by this function)
        │
        ├── Stage 1: TapInitialiserAgent (if manifest has personalization)
        │   ├── RUNS FIRST to set up context for all downstream agents
        │   ├── Reads sma_interaction_preferences from Gateway context (via session state)
        │   ├── Reads system-manifest.yaml to understand agent architecture
        │   ├── Generates personalized snippets for each per_agent_preferences key
        │   └── Stores snippets in session state via after_agent_callback:
        │       └── state["my_agent_user_preferences"] = "User prefers concise answers"
        │       └── state["input_validator_user_preferences"] = "Use friendly tone"
        │
        ├── Stage 2: InputValidator (if input_schema has required fields)
        │   ├── Validates required fields from AgentInputSchema
        │   ├── If fields missing → calls ask_clarifying_questions()
        │   └── Uses {input_validator_user_preferences} for tone/language
        │
        └── Stage 3: DeveloperAgent (always included)
            ├── Your business logic
            └── Uses {my_agent_user_preferences} in instruction

    ==========================================================================
    WHY INITIALISER RUNS FIRST
    ==========================================================================

    TapInitialiserAgent must run BEFORE other agents because:
    1. It sets state variables that downstream agents need
    2. InputValidator uses {input_validator_user_preferences} for question tone
    3. DeveloperAgent uses {my_agent_user_preferences} for behavior
    4. ADK substitutes {state_key} placeholders WHEN THE AGENT RUNS
       (not at pipeline construction time)

    ==========================================================================
    CALL CHAIN
    ==========================================================================

    server.py:94
        └── build_tap_agent()
            └── should_use_initialiser() → True
                └── wrap_with_full_pipeline() ← THIS FUNCTION
                    └── Returns SequentialAgent

    ==========================================================================
    WHEN TO USE THIS VS wrap_with_validation()
    ==========================================================================

    Use wrap_with_full_pipeline() when:
    - agent/system-manifest.yaml exists
    - personalization.enabled = true
    - state_schema.per_agent_preferences has entries

    Use wrap_with_validation() when:
    - No manifest or personalization disabled
    - Simpler pipeline (lower latency, fewer LLM calls)

    The choice is automatic via build_tap_agent() → should_use_initialiser().

    Args:
        developer_agent: The developer's root_agent (from agent/agent.py)
        input_schema: AgentInputSchema class (from agent/schemas.py)
        skip_validation: Force skip InputValidator (overrides TAP_SKIP_VALIDATION env)
        skip_initialiser: Force skip TapInitialiserAgent (overrides TAP_SKIP_INITIALISER env)

    Returns:
        SequentialAgent with [TapInitialiserAgent?, InputValidator?, DeveloperAgent]
        Returns unwrapped developer_agent if all optional stages skipped
    """
    from .initialiser import create_tap_initialiser_agent, should_use_initialiser
    from .manifest import load_system_manifest

    # Check skip flags with env var fallbacks
    if skip_validation is None:
        skip_validation = os.environ.get("TAP_SKIP_VALIDATION", "").lower() == "true"
    if skip_initialiser is None:
        skip_initialiser = os.environ.get("TAP_SKIP_INITIALISER", "").lower() == "true"

    # Build pipeline stages
    stages = []
    stage_num = 0

    # Stage 1: Initialisation (TapInitialiserAgent) - RUNS FIRST
    # Sets *_user_preferences state variables for all downstream agents
    if not skip_initialiser:
        manifest = load_system_manifest()
        if manifest.personalization.enabled:
            initialiser = create_tap_initialiser_agent(manifest)
            if initialiser:
                stages.append(initialiser)
                stage_num += 1
                # Use get_preference_keys() for consistent key detection across all sources
                pref_keys = manifest.get_preference_keys()
                logger.info(f"Pipeline stage {stage_num}: TapInitialiserAgent ({len(pref_keys)} preference keys)")

    # Stage 2: Input Validation (uses {input_validator_user_preferences} from Stage 1)
    if not skip_validation:
        required_fields = get_required_fields(input_schema)
        if required_fields:
            input_validator = create_input_validator(
                required_fields=required_fields,
                agent_name=developer_agent.name,
            )
            stages.append(input_validator)
            stage_num += 1
            logger.info(f"Pipeline stage {stage_num}: InputValidator ({len(required_fields)} fields)")

    # Stage 3: Developer Agent (always included)
    stages.append(developer_agent)
    stage_num += 1
    logger.info(f"Pipeline stage {stage_num}: {developer_agent.name}")

    # If only developer agent, return directly (no wrapper needed)
    if len(stages) == 1:
        logger.info("No pipeline stages needed, returning unwrapped agent")
        return developer_agent

    # Wrap in SequentialAgent
    pipeline_name = f"{developer_agent.name}Pipeline"
    logger.info(f"Created {pipeline_name} with {len(stages)} stages")

    return SequentialAgent(
        name=pipeline_name,
        description=(
            f"TAP pipeline for {developer_agent.name}: "
            f"initialisation → validation → execution"
        ),
        sub_agents=stages,
    )


__all__ = [
    # Main entry points
    "wrap_with_validation",
    "wrap_with_full_pipeline",
    # Field detection
    "get_required_fields",
    # Validator creation
    "create_input_validator",
    "generate_validator_prompt",
    "create_validated_input_schema",
    # Tool access
    "get_mesh_tools",
    # Constants
    "VALIDATION_MODEL",
    "CONFIDENCE_THRESHOLD",
    "UI_WIDGET_TO_QUESTION_TYPE",
    "PLATFORM_FIELDS",
]
