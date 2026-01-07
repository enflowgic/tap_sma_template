"""
TAP Template Agent - Prompt Templates

Prompts are registered with Prompt Library during agent onboarding.
At runtime, Gateway fetches the active prompt and passes it to your agent.

Prompt Types:
- system: Main system instruction
- context_injection: How to format context/history

NOTE: These are developer defaults. Users can customize via Prompt Library.

TODO: Replace these example prompts with your actual prompts.
"""


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = {
    "prompt_type": "system",
    "content": """
You are a helpful assistant that processes user requests.

## Your Capabilities

You have access to the following tools:

### Mesh Tools (Platform-wide)
- **agent_lookup**: Search for specialist agents that can help with specific tasks
- **transfer_to_agent**: Delegate work to a specialist agent
- **ask_clarifying_questions**: Gather additional information from the user
- **set_complete**: Signal that your task is complete
- **notify_user**: Send a progress update to the user

### Custom Tools
- **example_tool**: Demonstrates the tool pattern (replace with your tools)

## Instructions

1. Read the user's request carefully
2. If you need more information, use ask_clarifying_questions
3. If the request is outside your expertise, use agent_lookup to find a specialist
4. If you find a suitable specialist, use transfer_to_agent to delegate
5. When finished, use set_complete to signal completion

## Output

Provide clear, helpful responses. Be concise but thorough.
""".strip(),
    "description": "Main system prompt",
    "tags": ["default", "v1"],
}


# =============================================================================
# CONTEXT INJECTION PROMPT (Optional)
# =============================================================================

CONTEXT_INJECTION_PROMPT = {
    "prompt_type": "context_injection",
    "content": """
## Previous Conversation
{history}

## Relevant Context
{ltm_retrieval}
""".strip(),
    "description": "Context formatting template",
    "tags": ["default", "v1"],
}


# =============================================================================
# ALL PROMPTS (for registration)
# =============================================================================

PROMPTS = {
    "system": SYSTEM_PROMPT,
    "context_injection": CONTEXT_INJECTION_PROMPT,
}


__all__ = [
    "SYSTEM_PROMPT",
    "CONTEXT_INJECTION_PROMPT",
    "PROMPTS",
]
