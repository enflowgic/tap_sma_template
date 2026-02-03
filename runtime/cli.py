"""
TAP Template Agent - Local Development CLI

Interactive CLI for testing your agent locally before deployment.

Usage:
    python runtime/cli.py              # Interactive mode
    python runtime/cli.py "Do task"    # Single query mode

For production deployment:
    python runtime/server.py           # Start A2A server locally
    gcloud run deploy                  # Deploy to Cloud Run
"""

import asyncio
import os
import sys
from uuid import uuid4

# =============================================================================
# ENVIRONMENT SETUP
# =============================================================================

# Configure Vertex AI BEFORE importing google.genai
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "your-project-id")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

# Load .env file from deploy/ directory if exists
# Check multiple locations for flexibility
project_root = os.path.dirname(os.path.dirname(__file__))
env_paths = [
    os.path.join(project_root, "deploy", ".env"),  # Primary: deploy/.env
    os.path.join(os.path.dirname(__file__), ".env"),  # Fallback: runtime/.env (legacy)
]

for env_file in env_paths:
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
        break  # Stop after first found .env

# Add paths for imports
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# =============================================================================
# IMPORTS
# =============================================================================

from google.adk.runners import InMemoryRunner

# Developer's agent
from agent import agent

# TAP platform integration
from tap_wrapper import build_tap_agent, setup_tool_context, get_config

# Load configuration from tap-agent.yaml
config = get_config()

# Build TAP-wrapped agent (injects mesh tools, adds validation)
# For CLI testing, we use the raw agent without validation wrapper
# to keep interactions simpler during development
AGENT_NAME = config.slug
AGENT_METADATA = {
    "slug": config.slug,
    "display_name": config.display_name,
    "version": config.version,
    "model": config.model,
    "description": config.description,
}


# =============================================================================
# TOKEN EXTRACTION (for billing reporting)
# =============================================================================

def extract_token_counts(events: list) -> tuple[int, int]:
    """
    Extract token counts from ADK runner events.

    TAP billing needs input/output token counts. This extracts them
    from the LLM response events.

    Args:
        events: List of events from runner.run_async()

    Returns:
        Tuple of (input_tokens, output_tokens)
    """
    input_tokens = 0
    output_tokens = 0

    for event in events:
        if hasattr(event, 'content') and hasattr(event.content, 'usage_metadata'):
            metadata = event.content.usage_metadata
            if hasattr(metadata, 'prompt_token_count'):
                input_tokens += metadata.prompt_token_count or 0
            if hasattr(metadata, 'candidates_token_count'):
                output_tokens += metadata.candidates_token_count or 0

    return input_tokens, output_tokens


# =============================================================================
# INTERACTIVE MODE
# =============================================================================

async def run_interactive():
    """Interactive CLI for testing your agent."""
    runner = InMemoryRunner(agent=agent, app_name=AGENT_NAME)

    print("=" * 60)
    print(f"{AGENT_NAME} - Local Development Mode")
    print("=" * 60)
    print(f"Project: {os.environ.get('GOOGLE_CLOUD_PROJECT')}")
    print(f"Model: {os.environ.get('TAP_MODEL_NAME', 'gemini-3-flash-preview')}")
    print("=" * 60)
    print("\nCommands: 'test', 'status', 'quit'")
    print("Or type any prompt to interact with the agent.")
    print("-" * 60)

    session_id = f"dev-{uuid4().hex[:8]}"

    # Set up tool context for mesh tools
    setup_tool_context({
        "org_id": "dev-org",
        "user_id": "dev-user",
        "session_id": session_id,
        "trace_id": f"trace-{uuid4().hex[:16]}",
    })

    while True:
        try:
            user_input = input("\nUser: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not user_input:
            continue

        if user_input.lower() in ["quit", "exit", "q"]:
            print("Exiting...")
            break

        if user_input.lower() == "status":
            print("\n" + "=" * 40)
            print("Agent Configuration:")
            for key, value in AGENT_METADATA.items():
                if key == "input_schema":
                    print(f"  {key}: [JSON Schema]")
                else:
                    print(f"  {key}: {value}")
            print("=" * 40)
            continue

        if user_input.lower() == "test":
            user_input = "Hello! What can you help me with?"

        print("\n[Processing...]\n")

        try:
            events = []
            async for event in runner.run_async(
                user_id="dev-user",
                session_id=session_id,
                new_message=user_input,
            ):
                events.append(event)

                # Show progress
                if hasattr(event, 'content') and hasattr(event.content, 'parts'):
                    for part in event.content.parts:
                        if hasattr(part, 'function_call'):
                            print(f"  [Tool] {part.function_call.name}")

            # Extract tokens
            input_tokens, output_tokens = extract_token_counts(events)

            # Show final response
            for event in events:
                if event.is_final_response():
                    print("\n" + "=" * 60)
                    print("RESULT:")
                    print("=" * 60)
                    if hasattr(event.content, 'parts'):
                        for part in event.content.parts:
                            if hasattr(part, 'text'):
                                print(part.text)
                    print("=" * 60)
                    print(f"Tokens: {input_tokens} in / {output_tokens} out")

        except Exception as e:
            print(f"\n[ERROR]: {e}")
            import traceback
            traceback.print_exc()


# =============================================================================
# SINGLE QUERY MODE
# =============================================================================

async def run_once(prompt: str):
    """
    Run agent with a single prompt.

    Useful for testing and CI/CD pipelines.
    """
    runner = InMemoryRunner(agent=agent, app_name=AGENT_NAME)

    session_id = f"query-{uuid4().hex[:8]}"

    # Set up tool context
    setup_tool_context({
        "org_id": "dev-org",
        "user_id": "dev-user",
        "session_id": session_id,
        "trace_id": f"trace-{uuid4().hex[:16]}",
    })

    events = []
    async for event in runner.run_async(
        user_id="dev-user",
        session_id=session_id,
        new_message=prompt,
    ):
        events.append(event)

    # Extract tokens
    input_tokens, output_tokens = extract_token_counts(events)

    # Get final response
    output = ""
    for event in events:
        if event.is_final_response():
            if hasattr(event.content, 'parts'):
                for part in event.content.parts:
                    if hasattr(part, 'text'):
                        output = part.text
                        break

    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(output)
    print("=" * 60)
    print(f"Tokens: {input_tokens} in / {output_tokens} out")

    return {
        "output": output,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Single query mode
        prompt = " ".join(sys.argv[1:])
        asyncio.run(run_once(prompt))
    else:
        # Interactive mode
        asyncio.run(run_interactive())
