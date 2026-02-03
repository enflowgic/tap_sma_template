"""
TAP Template Agent - Developer Prompts

Define your agent's personality and instructions here.
You only need to provide the AGENT_DESCRIPTION - capabilities and instructions are optional.

At runtime, these are combined with TAP platform boilerplate automatically
by tap_wrapper.prompts.compose_system_prompt().

The final system prompt structure is:
    1. Your AGENT_DESCRIPTION (required)
    2. Platform mesh tools documentation (automatic)
    3. User preferences section (automatic - see below)
    4. Your AGENT_CAPABILITIES (optional)
    5. Your AGENT_INSTRUCTIONS (optional)
    6. Platform return behavior rules (automatic)

## Context Flow (How Gateway Sends Context to Your Agent)

Understanding context flow is important for SMA development:

1. **System Prompt**: Your prompt is built at import time from this file.
   Gateway does NOT inject history/LTM into your system prompt.

2. **History**: Gateway sends conversation history in params.context.
   The runtime server.py injects it into the USER MESSAGE, not the system prompt.
   This is done automatically - you don't need to handle it.

3. **LTM (Long-Term Memory)**: Gateway retrieves LTM from Cognee and sends it
   in params.context. The server.py puts it into session state for
   TapInitialiserAgent to process and summarize.

4. **SMA Interaction Preferences**: Gateway sends sma_interaction_preferences as a
   List[Dict] from Cognee. The server.py converts this to bullet-point text and stores
   in session state["sma_interaction_preferences"]. TapInitialiserAgent reads this and
   generates personalized instruction snippets for each agent.

## User Preferences (Automatic - No Action Required)

The TAP wrapper automatically includes a "History and Feedback Based User Preferences"
section in your agent's prompt. This section:

- Explains how the preference system works to the LLM
- Contains a state variable placeholder (e.g., {my_agent_user_preferences})
- Gets populated by TapInitialiserAgent at runtime with personalized guidance

ADK's `inject_session_state()` substitutes `{my_agent_user_preferences}` with the
actual value from session state before sending the prompt to the LLM.

The TapInitialiserAgent reads your system-manifest.yaml to understand which agents
need which preferences, then generates tailored snippets based on user feedback
stored in Cognee.

To customize which state key is used, define it in your system-manifest.yaml:
    state_schema:
      per_agent_preferences:
        my_agent_user_preferences:   # <-- This becomes the state key
          domain: "Your agent's domain"
          description: "What preferences this agent cares about"

You do NOT need to add any user preferences boilerplate to your prompts - it's
all handled automatically by the wrapper.
"""


# =============================================================================
# AGENT DESCRIPTION (Required)
# =============================================================================
# This is the core identity of your agent - who it is and what it does.
# Keep it focused on the agent's role, not on how it uses tools.

AGENT_DESCRIPTION = """
You are a helpful assistant that processes user requests.

Your role is to understand what the user needs and either:
- Handle the request directly using your capabilities
- Find and delegate to a specialist agent if needed
""".strip()


# =============================================================================
# AGENT CAPABILITIES (Optional)
# =============================================================================
# List your agent's specific capabilities beyond the mesh tools.
# Set to None if you don't need custom capabilities.

AGENT_CAPABILITIES = """
- Analyze user requests and determine the best approach
- Search for specialist agents when needed
- Coordinate multi-step tasks across specialists
- Summarize findings and present clear results
""".strip()


# =============================================================================
# AGENT INSTRUCTIONS (Optional)
# =============================================================================
# Specific behavioral instructions for your agent.
# Set to None if the default platform behavior is sufficient.

AGENT_INSTRUCTIONS = """
1. Read the user's request carefully
2. If you need more information, use ask_clarifying_questions
3. If the request needs a specialist, use agent_lookup then transfer_to_agent
4. Use your tools to accomplish the task
5. When finished, call transfer_back_to_parent() with your results

Be clear, helpful, and concise.
""".strip()


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "AGENT_DESCRIPTION",
    "AGENT_CAPABILITIES",
    "AGENT_INSTRUCTIONS",
]
