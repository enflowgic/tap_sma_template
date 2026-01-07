#!/usr/bin/env python3
"""
TAP Agent Registration Script

Registers your agent with the Cognee Registry so it can be discovered
by the Master Agent via semantic search.

This script is automatically run by the TAP GitHub App during onboarding,
but you can also run it manually for testing or updates.

Usage:
    # After deploying to Vertex AI:
    python register_agent.py --vertex-resource-name projects/.../reasoningEngines/...

    # After deploying to Cloud Run:
    python register_agent.py --cloud-run-url https://my-agent-xxx.run.app

    # Override discovery tier (defaults to 'tertiary' for marketplace):
    python register_agent.py --vertex-resource-name ... --tier secondary

Prerequisites:
    - Agent must be deployed first (run deploy_vertex.py or deploy to Cloud Run)
    - COGNEE_REGISTRY_URL environment variable set (or use default)
    - Authenticated with Google Cloud (gcloud auth application-default login)
"""

import os
import sys
import argparse
import json
from pathlib import Path
from typing import Optional

import httpx
import yaml


# =============================================================================
# CONFIGURATION
# =============================================================================

# Configure these via environment variables or update defaults for your TAP deployment
COGNEE_REGISTRY_URL = os.getenv("COGNEE_REGISTRY_URL")
if not COGNEE_REGISTRY_URL:
    raise ValueError(
        "COGNEE_REGISTRY_URL environment variable is required. "
        "Set it to your TAP Cognee Registry endpoint."
    )

PROMPT_LIBRARY_URL = os.getenv("PROMPT_LIBRARY_URL")
if not PROMPT_LIBRARY_URL:
    raise ValueError(
        "PROMPT_LIBRARY_URL environment variable is required. "
        "Set it to your TAP Prompt Library endpoint."
    )


# =============================================================================
# HELPERS
# =============================================================================

def get_identity_token(audience: str) -> str:
    """Get identity token for Cloud Run service-to-service auth."""
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token
        auth_req = google.auth.transport.requests.Request()
        return google.oauth2.id_token.fetch_id_token(auth_req, audience)
    except Exception as e:
        print(f"[WARN] Could not get ID token: {e}")
        print("       Continuing without authentication (may fail for protected endpoints)")
        return ""


def load_manifest() -> dict:
    """Load tap-agent.yaml manifest from current directory or parent."""
    for path in [Path("tap-agent.yaml"), Path("../tap-agent.yaml")]:
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f)

    raise FileNotFoundError(
        "tap-agent.yaml not found. "
        "Please run this script from the agent root directory."
    )


def extract_json_schema(file_path: str, class_name: str) -> dict:
    """
    Extract JSON schema from a Pydantic model.

    This imports the module and calls model_json_schema().
    For sandboxed extraction, the platform uses AST parsing instead.
    """
    import importlib.util

    # Convert file path to module path
    spec = importlib.util.spec_from_file_location("schema_module", file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["schema_module"] = module
    spec.loader.exec_module(module)

    # Get the class and extract schema
    schema_class = getattr(module, class_name)
    return schema_class.model_json_schema()


def build_agent_card(
    manifest: dict,
    vertex_resource_name: Optional[str] = None,
    cloud_run_url: Optional[str] = None,
) -> dict:
    """Build the agent card from manifest and deployment info."""
    metadata = manifest.get("metadata", {})
    provider = manifest.get("provider", {})
    deployment = manifest.get("deployment", {})
    capabilities = manifest.get("capabilities", {})
    pricing = manifest.get("pricing")
    discovery = manifest.get("discovery", {})

    # Extract input schema
    schemas_config = manifest.get("schemas", {})
    input_schema = {}
    if schemas_config.get("input"):
        try:
            input_schema = extract_json_schema(
                schemas_config["input"]["file"],
                schemas_config["input"]["class"]
            )
        except Exception as e:
            print(f"[WARN] Could not extract input schema: {e}")
            print("       Using empty schema (platform will extract during onboarding)")

    # Determine agent_type: 'master_agent' or 'sma' (default)
    # Master Agent is special - all other agents are SMAs
    agent_type = metadata.get("agent_type", "sma")
    if agent_type not in ("master_agent", "sma"):
        agent_type = "sma"

    # Build the agent card
    agent_card = {
        "agent_slug": metadata.get("slug"),
        "displayName": metadata.get("display_name"),  # Use displayName for Cognee compatibility
        "display_name": metadata.get("display_name"),  # Also keep display_name for backwards compat
        "description": metadata.get("description", "").strip(),
        "version": metadata.get("version", "0.1.0"),
        "agent_type": agent_type,  # Required: 'master_agent' or 'sma'
        "provider": {
            "organization": provider.get("organization"),
            "organization_name": provider.get("organization_name"),
        },
        "capabilities": {
            "primary": capabilities.get("primary", []),
            "secondary": capabilities.get("secondary", []),
        },
        "skills": manifest.get("skills", []),
        "input_schema": input_schema,
        # Master Agent discovery fields
        "discovery": {
            "tier": discovery.get("tier", "tertiary"),  # primary | secondary | tertiary
            "is_public": discovery.get("is_public", True),
            "is_active": discovery.get("is_active", True),
        },
        "deployment": {
            "vertex_resource_name": vertex_resource_name,
            "cloud_run_url": cloud_run_url,
            "project_id": os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            "region": deployment.get("region", "us-central1"),
            "model": deployment.get("model", "gemini-3-flash-preview"),
            "timeout_seconds": deployment.get("resources", {}).get("timeout_seconds", 120),
        },
        "metadata": {
            "category": "Custom",
            "tags": manifest.get("tags", []),
            "documentation_url": provider.get("documentation_url"),
            "support_email": provider.get("support_email"),
        },
    }

    # Add pricing if specified
    if pricing:
        agent_card["pricing"] = {
            "developer_cost_per_1k_tokens": pricing.get("developer_cost_per_1k", 0),
            "sales_price_per_1k_tokens": pricing.get("sales_price_per_1k", 0),
            "currency": pricing.get("currency", "USD"),
        }

    return agent_card


# =============================================================================
# VALIDATION
# =============================================================================

REQUIRED_FIELDS = [
    ("agent_slug", "metadata.slug in tap-agent.yaml"),
    ("displayName", "metadata.display_name in tap-agent.yaml"),
    ("description", "metadata.description in tap-agent.yaml"),
    ("agent_type", "metadata.agent_type in tap-agent.yaml (master_agent or sma)"),
    ("input_schema", "schemas.input in tap-agent.yaml"),
]

REQUIRED_INPUT_SCHEMA_FIELDS = ["type", "properties"]


def validate_agent_card(agent_card: dict) -> list[str]:
    """
    Validate agent card has all required fields for Cognee registration.

    Returns list of error messages (empty if valid).
    """
    errors = []

    # Check required top-level fields
    for field, source in REQUIRED_FIELDS:
        value = agent_card.get(field)
        if not value:
            errors.append(f"Missing required field '{field}' - set {source}")
        elif field == "agent_type" and value not in ("master_agent", "sma"):
            errors.append(f"Invalid agent_type '{value}' - must be 'master_agent' or 'sma'")

    # Validate input_schema structure
    input_schema = agent_card.get("input_schema", {})
    if input_schema:
        if input_schema.get("type") != "object":
            errors.append("input_schema must have 'type': 'object'")
        if "properties" not in input_schema:
            errors.append("input_schema must have 'properties' defined")
    else:
        errors.append("input_schema is required - define schemas.input in tap-agent.yaml")

    # Validate provider
    provider = agent_card.get("provider", {})
    if not provider.get("organization"):
        errors.append("Missing provider.organization - set provider.organization in tap-agent.yaml")

    # Validate deployment endpoint
    deployment = agent_card.get("deployment", {})
    if not deployment.get("vertex_resource_name") and not deployment.get("cloud_run_url"):
        errors.append("Missing deployment endpoint - provide --vertex-resource-name or --cloud-run-url")

    return errors


# =============================================================================
# REGISTRATION
# =============================================================================

def register_with_cognee(agent_card: dict) -> dict:
    """Register the agent card with Cognee Registry."""
    discovery = agent_card.get("discovery", {})
    print("=" * 60)
    print("TAP Agent Registration")
    print("=" * 60)
    print(f"Registry URL: {COGNEE_REGISTRY_URL}")
    print(f"Agent Slug:   {agent_card['agent_slug']}")
    print(f"Version:      {agent_card['version']}")
    print(f"Tier:         {discovery.get('tier', 'tertiary')}")
    print(f"Is Public:    {discovery.get('is_public', True)}")
    print(f"Is Active:    {discovery.get('is_active', True)}")
    print("=" * 60)

    # Get auth headers
    headers = {"Content-Type": "application/json"}
    id_token = get_identity_token(COGNEE_REGISTRY_URL)
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"

    # Prepare request
    request_body = {
        "agent_slug": agent_card["agent_slug"],
        "agent_card": agent_card
    }

    try:
        response = httpx.post(
            f"{COGNEE_REGISTRY_URL}/agents/index",
            json=request_body,
            headers=headers,
            timeout=30.0
        )

        if response.status_code == 200:
            result = response.json()
            print("\n[SUCCESS] Agent registered with Cognee Registry!")
            print(f"  Agent ID: {result.get('agent_id', 'N/A')}")
            print(f"  Status:   {result.get('status', 'indexed')}")
            return result

        elif response.status_code == 409:
            print("\n[INFO] Agent already registered. Updating...")
            response = httpx.put(
                f"{COGNEE_REGISTRY_URL}/agents/{agent_card['agent_slug']}",
                json=agent_card,
                headers=headers,
                timeout=30.0
            )
            if response.status_code == 200:
                print("[SUCCESS] Agent updated successfully!")
                return response.json()
            else:
                print(f"[ERROR] Update failed: {response.status_code}")
                print(response.text[:500])
                return {"error": response.text}

        else:
            print(f"\n[ERROR] Registration failed: {response.status_code}")
            print(response.text[:500])
            return {"error": response.text}

    except httpx.TimeoutException:
        print("\n[ERROR] Request timed out")
        return {"error": "timeout"}
    except Exception as e:
        print(f"\n[ERROR] Registration failed: {e}")
        return {"error": str(e)}


def verify_registration(agent_slug: str) -> bool:
    """Verify the agent is registered and searchable."""
    print("\nVerifying registration...")

    headers = {"Content-Type": "application/json"}
    id_token = get_identity_token(COGNEE_REGISTRY_URL)
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"

    try:
        response = httpx.post(
            f"{COGNEE_REGISTRY_URL}/agents/search",
            json={"query": agent_slug.replace("-", " "), "limit": 5},
            headers=headers,
            timeout=30.0
        )

        if response.status_code == 200:
            results = response.json().get("results", [])
            for r in results:
                if r.get("agent_slug") == agent_slug:
                    print(f"[OK] Agent found in search results")
                    print(f"     Relevance: {r.get('relevance_score', 'N/A')}")
                    return True

            print(f"[WARN] Agent '{agent_slug}' not found in search results")
            print(f"       (This may be normal - embeddings can take time to index)")
            return False
        else:
            print(f"[ERROR] Search failed: {response.status_code}")
            return False

    except Exception as e:
        print(f"[ERROR] Verification failed: {e}")
        return False


# =============================================================================
# PROMPT LIBRARY REGISTRATION
# =============================================================================

def load_prompts() -> dict:
    """Load prompts from the agent's prompts.py module."""
    # Try to import PROMPTS from the agent module
    for module_path in ["my_agent.prompts", "prompts"]:
        try:
            import importlib
            prompts_module = importlib.import_module(module_path)
            if hasattr(prompts_module, "PROMPTS"):
                return prompts_module.PROMPTS
        except ImportError:
            continue

    # Fallback: return empty dict (agent will use Gateway-provided prompts only)
    print("[WARN] No PROMPTS dict found in prompts.py - skipping prompt registration")
    return {}


def register_prompts_with_library(agent_slug: str, prompts: dict) -> dict:
    """
    Register developer default prompts with Prompt Library.

    Args:
        agent_slug: The agent's unique identifier (use underscores, not hyphens)
        prompts: Dict of {prompt_type: prompt_config}

    Returns:
        Dict with registration results per prompt type
    """
    print("\n" + "=" * 60)
    print("Prompt Library Registration")
    print("=" * 60)
    print(f"Service URL: {PROMPT_LIBRARY_URL}")
    print(f"Agent Slug:  {agent_slug}")
    print(f"Prompts:     {list(prompts.keys())}")
    print("=" * 60)

    # Get auth headers
    headers = {"Content-Type": "application/json"}
    id_token = get_identity_token(PROMPT_LIBRARY_URL)
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"

    results = {}

    for prompt_type, prompt_config in prompts.items():
        try:
            # Prompt Library uses underscores in agent slugs
            normalized_slug = agent_slug.replace("-", "_")

            response = httpx.post(
                f"{PROMPT_LIBRARY_URL}/agents/{normalized_slug}/default-prompt",
                params={"prompt_type": prompt_type},
                json={
                    "content": prompt_config["content"],
                    "description": prompt_config.get("description", f"Default {prompt_type} prompt"),
                    "tags": prompt_config.get("tags", ["default"]),
                },
                headers=headers,
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json().get("data", {})
                print(f"  [{prompt_type}] Registered v{data.get('version', 1)}")
                results[prompt_type] = {"status": "success", "version": data.get("version")}
            else:
                print(f"  [{prompt_type}] Failed: {response.status_code}")
                print(f"             {response.text[:200]}")
                results[prompt_type] = {"status": "error", "error": response.text[:200]}

        except httpx.TimeoutException:
            print(f"  [{prompt_type}] Timeout")
            results[prompt_type] = {"status": "error", "error": "timeout"}
        except Exception as e:
            print(f"  [{prompt_type}] Error: {e}")
            results[prompt_type] = {"status": "error", "error": str(e)}

    return results


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Register TAP agent with Cognee Registry"
    )
    parser.add_argument(
        "--vertex-resource-name",
        type=str,
        help="Vertex AI Reasoning Engine resource name"
    )
    parser.add_argument(
        "--cloud-run-url",
        type=str,
        help="Cloud Run service URL"
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip verification step"
    )
    parser.add_argument(
        "--skip-prompts",
        action="store_true",
        help="Skip Prompt Library registration"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print agent card without registering"
    )
    parser.add_argument(
        "--tier",
        type=str,
        choices=["primary", "secondary", "tertiary"],
        help="Override discovery tier (primary=equipped, secondary=private, tertiary=marketplace)"
    )

    args = parser.parse_args()

    # Load manifest
    try:
        manifest = load_manifest()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # Get deployment info from args or environment
    vertex_resource_name = args.vertex_resource_name or os.getenv("VERTEX_RESOURCE_NAME")
    cloud_run_url = args.cloud_run_url or os.getenv("CLOUD_RUN_URL")

    if not vertex_resource_name and not cloud_run_url:
        print("[ERROR] Deployment endpoint required.")
        print("\nProvide one of:")
        print("  --vertex-resource-name projects/.../reasoningEngines/...")
        print("  --cloud-run-url https://my-agent-xxx.run.app")
        print("\nOr set environment variables:")
        print("  VERTEX_RESOURCE_NAME or CLOUD_RUN_URL")
        sys.exit(1)

    # Build agent card
    agent_card = build_agent_card(manifest, vertex_resource_name, cloud_run_url)

    # Override tier from CLI if provided
    if args.tier:
        agent_card["discovery"]["tier"] = args.tier

    # Dry run - just print the card
    if args.dry_run:
        print("\n[DRY RUN] Agent card that would be registered:")
        print(json.dumps(agent_card, indent=2))
        sys.exit(0)

    # Validate agent card before registration
    validation_errors = validate_agent_card(agent_card)
    if validation_errors:
        print("\n[ERROR] Agent card validation failed:")
        for error in validation_errors:
            print(f"  - {error}")
        print("\nPlease fix these issues in tap-agent.yaml and try again.")
        sys.exit(1)

    # Register
    result = register_with_cognee(agent_card)

    if "error" not in result:
        # Verify Cognee registration
        if not args.skip_verify:
            verify_registration(agent_card["agent_slug"])

        # Register prompts with Prompt Library
        if not args.skip_prompts:
            prompts = load_prompts()
            if prompts:
                prompt_results = register_prompts_with_library(
                    agent_slug=agent_card["agent_slug"],
                    prompts=prompts
                )

                # Check for failures
                failures = [k for k, v in prompt_results.items() if v.get("status") != "success"]
                if failures:
                    print(f"\n[WARN] Some prompts failed to register: {failures}")
                    print("       Gateway will use fallback behavior until prompts are registered.")

        print("\n" + "=" * 60)
        print("Registration Complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Test discovery via Master Agent:")
        print(f'   "Find me an agent that can {agent_card["capabilities"]["primary"][0] if agent_card["capabilities"]["primary"] else "help"}"')
        print("\n2. Verify in Cognee directly:")
        print(f"   curl {COGNEE_REGISTRY_URL}/agents/{agent_card['agent_slug']}")
        print("\n3. Verify prompts in Prompt Library:")
        normalized_slug = agent_card['agent_slug'].replace('-', '_')
        print(f"   curl {PROMPT_LIBRARY_URL}/prompts/{normalized_slug}")
        print("\n4. Test via TAP UI")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
