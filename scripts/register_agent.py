#!/usr/bin/env python3
"""
TAP Agent Registration Script

Registers your agent with the Cognee Registry so it can be discovered
by the Master Agent via semantic search.

AUTHENTICATION REQUIRED:
    This script requires authentication with the TAP platform.
    You must have a valid TAP account with developer or admin permissions.

CONFIGURATION:
    Billing fields can be provided via CLI arguments OR environment variables.
    CLI arguments take precedence over environment variables.

    Environment Variables (set in deploy/.env):
        TAP_OWNER_ORG_ID              - Owner organization UUID
        TAP_OWNER_USER_ID             - Owner user UUID
        TAP_INPUT_COGS_NANODOLLARS    - Input COGS per token (nanodollars)
        TAP_INPUT_MARGIN_NANODOLLARS  - Input margin per token (nanodollars)
        TAP_OUTPUT_COGS_NANODOLLARS   - Output COGS per token (nanodollars)
        TAP_OUTPUT_MARGIN_NANODOLLARS - Output margin per token (nanodollars)

Usage:
    # Login first (credentials are cached in ~/.tap/credentials.json):
    python register_agent.py --login

    # Option 1: Using environment variables (recommended)
    # First, configure deploy/.env with your billing settings, then:
    source deploy/.env
    python register_agent.py --cloud-run-url https://my-agent-xxx.run.app

    # Option 2: Using CLI arguments (overrides env vars)
    python register_agent.py \\
        --cloud-run-url https://my-agent-xxx.run.app \\
        --owner-org-id <your-org-uuid> \\
        --owner-user-id <your-user-uuid> \\
        --input-cogs 0 \\
        --input-margin 10000 \\
        --output-cogs 0 \\
        --output-margin 12000

    # Override discovery tier (defaults to 'tertiary' for marketplace):
    python register_agent.py --cloud-run-url ... --tier secondary

    # Dry run (preview without registering):
    python register_agent.py --cloud-run-url ... --dry-run

    # Logout (clear cached credentials):
    python register_agent.py --logout

Prerequisites:
    - Authenticated with TAP platform (developer or admin account)
    - Agent must be deployed to Cloud Run first
    - COGNEE_REGISTRY_URL environment variable set
    - All 6 billing fields are REQUIRED (via CLI or env vars)
"""

import os
import sys
import argparse
import json
import getpass
from pathlib import Path
from typing import Optional
from datetime import datetime

import httpx
import yaml


# =============================================================================
# CONFIGURATION
# =============================================================================

# TAP Platform URLs
TAP_BFF_URL = os.getenv("TAP_BFF_URL", "https://platform.tailoredagents.ai")

# Cognee Registry URL (for agent registration)
COGNEE_REGISTRY_URL = os.getenv("COGNEE_REGISTRY_URL")

# Credentials storage location
TAP_CREDENTIALS_DIR = Path.home() / ".tap"
TAP_CREDENTIALS_FILE = TAP_CREDENTIALS_DIR / "credentials.json"

# Allowed email domains for agent registration (empty = all TAP users allowed)
# Set to ["tailoredagents.ai"] to restrict to internal team only
ALLOWED_EMAIL_DOMAINS = os.getenv("TAP_ALLOWED_DOMAINS", "tailoredagents.ai").split(",")
ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in ALLOWED_EMAIL_DOMAINS if d.strip()]


def _get_env_int(name: str) -> Optional[int]:
    """
    Get an integer from environment variable, or None if not set.

    Used to provide environment variable defaults for CLI arguments.
    """
    value = os.getenv(name)
    if value is not None:
        try:
            return int(value)
        except ValueError:
            print(f"[WARN] Environment variable {name}={value} is not a valid integer")
    return None


# =============================================================================
# TAP AUTHENTICATION
# =============================================================================

class TAPAuthError(Exception):
    """Raised when TAP authentication fails."""
    pass


def get_credentials_path() -> Path:
    """Get the path to the credentials file, creating the directory if needed."""
    TAP_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    return TAP_CREDENTIALS_FILE


def load_cached_credentials() -> Optional[dict]:
    """Load cached credentials from ~/.tap/credentials.json if they exist and are valid."""
    creds_file = get_credentials_path()
    if not creds_file.exists():
        return None

    try:
        with open(creds_file) as f:
            creds = json.load(f)

        # Check if we have the required fields
        if not creds.get("access_token") or not creds.get("user"):
            return None

        # Note: Token expiry is checked server-side when we use it
        # We don't validate expiry here to allow refresh tokens to work
        return creds

    except (json.JSONDecodeError, IOError) as e:
        print(f"[WARN] Could not load cached credentials: {e}")
        return None


def save_credentials(creds: dict) -> None:
    """Save credentials to ~/.tap/credentials.json."""
    creds_file = get_credentials_path()

    # Ensure the credentials file is only readable by the owner
    try:
        with open(creds_file, "w") as f:
            json.dump(creds, f, indent=2)

        # Set file permissions to owner-only (Unix)
        try:
            os.chmod(creds_file, 0o600)
        except (OSError, AttributeError):
            pass  # Windows doesn't support chmod the same way

        print(f"[INFO] Credentials saved to {creds_file}")

    except IOError as e:
        print(f"[WARN] Could not save credentials: {e}")


def clear_credentials() -> None:
    """Clear cached credentials."""
    creds_file = get_credentials_path()
    if creds_file.exists():
        creds_file.unlink()
        print("[INFO] Credentials cleared successfully.")
    else:
        print("[INFO] No cached credentials to clear.")


def login_interactive() -> dict:
    """
    Interactively login to TAP platform.

    Returns:
        dict with access_token, refresh_token, and user info
    """
    print("=" * 60)
    print("TAP Platform Authentication")
    print("=" * 60)
    print(f"Platform: {TAP_BFF_URL}")
    print()

    # Get email
    email = input("Email: ").strip()
    if not email:
        raise TAPAuthError("Email is required")

    # Check email domain restriction
    if ALLOWED_EMAIL_DOMAINS:
        email_domain = email.split("@")[-1].lower()
        if email_domain not in ALLOWED_EMAIL_DOMAINS:
            raise TAPAuthError(
                f"Registration is restricted to users from: {', '.join(ALLOWED_EMAIL_DOMAINS)}\n"
                f"Your email domain '{email_domain}' is not authorized."
            )

    # Get password
    password = getpass.getpass("Password: ")
    if not password:
        raise TAPAuthError("Password is required")

    print("\n[INFO] Authenticating...")

    # Call the BFF login endpoint
    try:
        response = httpx.post(
            f"{TAP_BFF_URL}/api/auth/login",
            json={"email": email, "password": password},
            timeout=30.0,
            follow_redirects=True,
        )

        if response.status_code == 200:
            data = response.json()

            # Handle MFA requirement
            if data.get("requiresMfa"):
                print("\n[INFO] MFA verification required.")
                mfa_code = input("Enter MFA code: ").strip()

                mfa_response = httpx.post(
                    f"{TAP_BFF_URL}/api/auth/verify-mfa",
                    json={
                        "tempToken": data.get("tempToken"),
                        "code": mfa_code,
                    },
                    timeout=30.0,
                )

                if mfa_response.status_code == 200:
                    data = mfa_response.json()
                else:
                    raise TAPAuthError(f"MFA verification failed: {mfa_response.text}")

            # Verify we got tokens
            if not data.get("accessToken"):
                raise TAPAuthError("Login succeeded but no access token received")

            # Verify user has developer or admin permissions
            user = data.get("user", {})
            is_developer = user.get("isDeveloper", False)
            is_platform_admin = user.get("isPlatformAdmin", False)

            if not is_developer and not is_platform_admin:
                raise TAPAuthError(
                    "You must have Developer or Platform Admin permissions to register agents.\n"
                    "Contact your organization admin to request developer access."
                )

            # Build credentials object
            creds = {
                "access_token": data["accessToken"],
                "refresh_token": data.get("refreshToken"),
                "user": {
                    "id": user.get("id"),
                    "email": user.get("email"),
                    "name": user.get("name"),
                    "org_id": user.get("organizationId"),
                    "org_name": user.get("organizationName"),
                    "is_developer": is_developer,
                    "is_platform_admin": is_platform_admin,
                },
                "authenticated_at": datetime.utcnow().isoformat(),
            }

            print(f"\n[SUCCESS] Authenticated as {user.get('email')}")
            print(f"  Organization: {user.get('organizationName', 'N/A')}")
            print(f"  Developer:    {is_developer}")
            print(f"  Admin:        {is_platform_admin}")

            return creds

        elif response.status_code == 401:
            raise TAPAuthError("Invalid email or password")
        elif response.status_code == 403:
            error_data = response.json() if response.text else {}
            raise TAPAuthError(error_data.get("error", "Account locked or disabled"))
        else:
            raise TAPAuthError(f"Login failed: {response.status_code} - {response.text[:200]}")

    except httpx.RequestError as e:
        raise TAPAuthError(f"Could not connect to TAP platform: {e}")


def refresh_access_token(creds: dict) -> Optional[dict]:
    """
    Refresh the access token using the refresh token.

    Returns:
        Updated credentials dict, or None if refresh failed
    """
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        return None

    try:
        response = httpx.post(
            f"{TAP_BFF_URL}/api/auth/refresh",
            json={"refreshToken": refresh_token},
            timeout=30.0,
        )

        if response.status_code == 200:
            data = response.json()
            creds["access_token"] = data["accessToken"]
            if data.get("refreshToken"):
                creds["refresh_token"] = data["refreshToken"]
            creds["refreshed_at"] = datetime.utcnow().isoformat()
            return creds
        else:
            return None

    except httpx.RequestError:
        return None


def ensure_authenticated() -> dict:
    """
    Ensure the user is authenticated with TAP platform.

    Checks for cached credentials first, prompts for login if needed.

    Returns:
        dict with user info and access_token

    Raises:
        TAPAuthError if authentication fails
    """
    # Try cached credentials
    creds = load_cached_credentials()

    if creds:
        # Verify the token is still valid by making a test request
        try:
            response = httpx.get(
                f"{TAP_BFF_URL}/api/auth/me",
                headers={"Authorization": f"Bearer {creds['access_token']}"},
                timeout=10.0,
            )

            if response.status_code == 200:
                print(f"[INFO] Authenticated as {creds['user'].get('email')}")
                return creds

            elif response.status_code == 401:
                # Try refreshing the token
                print("[INFO] Access token expired, attempting refresh...")
                refreshed = refresh_access_token(creds)
                if refreshed:
                    save_credentials(refreshed)
                    print(f"[INFO] Token refreshed for {refreshed['user'].get('email')}")
                    return refreshed
                else:
                    print("[INFO] Token refresh failed, please login again.")

        except httpx.RequestError as e:
            print(f"[WARN] Could not validate cached credentials: {e}")

    # Need to login interactively
    print("\n[INFO] TAP authentication required.")
    creds = login_interactive()
    save_credentials(creds)
    return creds


def get_tap_auth_headers(creds: dict) -> dict:
    """Get HTTP headers for authenticated TAP API requests."""
    return {
        "Authorization": f"Bearer {creds['access_token']}",
        "Content-Type": "application/json",
        "X-TAP-User-Id": creds["user"].get("id", ""),
        "X-TAP-Org-Id": creds["user"].get("org_id", ""),
    }


# =============================================================================
# ENVIRONMENT VALIDATION (lazy - only when needed)
# =============================================================================

def validate_required_urls() -> None:
    """
    Validate required environment variables are set.

    Raises:
        SystemExit if required URLs are not configured.
    """
    errors = []

    if not COGNEE_REGISTRY_URL:
        errors.append("COGNEE_REGISTRY_URL - Required for agent registration")

    if errors:
        print("=" * 60)
        print("ERROR: Missing required environment variables:")
        print("=" * 60)
        for error in errors:
            print(f"  - {error}")
        print("\nSet these in your environment or .env file:")
        print("  export COGNEE_REGISTRY_URL=https://tap-cognee-registry-xxx.run.app")
        sys.exit(1)


# =============================================================================
# SERVICE-TO-SERVICE AUTH (for Cloud Run endpoints)
# =============================================================================

def get_identity_token(audience: str) -> str:
    """Get identity token for Cloud Run service-to-service auth."""
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token
        auth_req = google.auth.transport.requests.Request()
        return google.oauth2.id_token.fetch_id_token(auth_req, audience)
    except Exception as e:
        print(f"[WARN] Could not get GCP ID token: {e}")
        print("       Will use TAP user token instead.")
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


def get_existing_agent(agent_slug: str, creds: dict) -> Optional[dict]:
    """
    Fetch existing agent from Cognee to preserve billing data.

    CRITICAL: This prevents data loss when re-registering an agent.
    The upsert in Cognee OVERWRITES pricing fields, so we must
    fetch and re-send them to preserve existing values.

    Args:
        agent_slug: The agent's unique identifier
        creds: TAP authentication credentials
    """
    # Use TAP user auth
    headers = get_tap_auth_headers(creds)

    # Also try GCP ID token for service-to-service auth (some environments)
    id_token = get_identity_token(COGNEE_REGISTRY_URL)
    if id_token:
        headers["X-GCP-ID-Token"] = id_token

    try:
        response = httpx.get(
            f"{COGNEE_REGISTRY_URL}/agents/{agent_slug}",
            headers=headers,
            timeout=30.0
        )

        if response.status_code == 200:
            data = response.json()
            print(f"[INFO] Found existing agent registration")
            print(f"  Owner Org:     {data.get('owner_org_id', 'N/A')}")
            print(f"  Input COGS:    {data.get('input_agent_cogs_per_token_nanodollars', 'N/A')}")
            print(f"  Input Margin:  {data.get('input_agent_margin_per_token_nanodollars', 'N/A')}")
            print(f"  Output COGS:   {data.get('output_agent_cogs_per_token_nanodollars', 'N/A')}")
            print(f"  Output Margin: {data.get('output_agent_margin_per_token_nanodollars', 'N/A')}")
            return data
        elif response.status_code == 404:
            print("[INFO] Agent not found - will create new registration")
            return None
        else:
            print(f"[WARN] Could not fetch existing agent: {response.status_code}")
            return None

    except Exception as e:
        print(f"[WARN] Failed to fetch existing agent: {e}")
        return None


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
    cloud_run_url: str,
) -> dict:
    """
    Build the agent card from manifest and deployment info.

    Args:
        manifest: The parsed tap-agent.yaml manifest
        cloud_run_url: Cloud Run service URL (REQUIRED)

    Returns:
        A2A-compliant agent card dict for Cognee registration
    """
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
        # Identity (A2A standard)
        "name": metadata.get("slug"),  # A2A uses "name" as primary identifier
        "agent_slug": metadata.get("slug"),
        "displayName": metadata.get("display_name"),  # Use displayName for Cognee compatibility
        "display_name": metadata.get("display_name"),  # Also keep display_name for backwards compat
        "description": metadata.get("description", "").strip(),
        "version": metadata.get("version", "0.1.0"),
        "protocolVersion": "1.0",  # A2A protocol version
        "agent_type": agent_type,  # Required: 'master_agent' or 'sma'
        # Endpoint URLs (BOTH required for compatibility)
        "url": cloud_run_url,  # REQUIRED by Cognee validation
        "cloud_run_url": cloud_run_url,  # Gateway reads this for SMA invocation
        # A2A Protocol: Supported interfaces for JSON-RPC communication
        "supportedInterfaces": [{
            "protocol": "json-rpc",
            "endpoint": cloud_run_url,
            "version": "2.0",
        }],
        # Provider
        "provider": {
            "organization": provider.get("organization"),
            "organization_name": provider.get("organization_name"),
        },
        "capabilities": {
            "primary": capabilities.get("primary", []),
            "secondary": capabilities.get("secondary", []),
            "streaming": capabilities.get("streaming", False),
            "pushNotifications": capabilities.get("pushNotifications", False),
            "stateTransitionHistory": capabilities.get("stateTransitionHistory", True),
        },
        # I/O Modes (A2A requirement)
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        # Skills (IDs must be kebab-case per Cognee regex: ^[a-z0-9][a-z0-9-]*[a-z0-9]$)
        "skills": manifest.get("skills", []),
        "input_schema": input_schema,
        # Master Agent discovery fields
        "discovery": {
            "tier": discovery.get("tier", "tertiary"),  # primary | secondary | tertiary
            "is_public": discovery.get("is_public", True),
            "is_active": discovery.get("is_active", True),
        },
        # Tags for categorization and search
        "tags": manifest.get("tags", []),
        "deployment": {
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

    # Validate deployment endpoint (Cloud Run URL is REQUIRED)
    deployment = agent_card.get("deployment", {})
    if not deployment.get("cloud_run_url"):
        errors.append("Missing deployment endpoint - provide --cloud-run-url")

    return errors


# =============================================================================
# REGISTRATION
# =============================================================================

def register_with_cognee(
    agent_card: dict,
    owner_org_id: str,
    owner_user_id: str,
    input_cogs: int,
    input_margin: int,
    output_cogs: int,
    output_margin: int,
    creds: dict,
    tier: str = "tertiary",
    dry_run: bool = False,
) -> dict:
    """
    Register the agent card with Cognee Registry.

    BILLING CRITICAL: All 6 fields are REQUIRED - no silent defaults.
    The CLI validation ensures all fields are provided before this function is called.

    Args:
        agent_card: The A2A-compliant agent card
        owner_org_id: Owner organization UUID (REQUIRED)
        owner_user_id: Owner user UUID (REQUIRED)
        input_cogs: Input COGS in nanodollars per token
        input_margin: Input margin in nanodollars per token
        output_cogs: Output COGS in nanodollars per token
        output_margin: Output margin in nanodollars per token
        creds: TAP authentication credentials (REQUIRED)
        tier: Agent tier (primary, secondary, tertiary)
        dry_run: If True, print payload without sending
    """
    discovery = agent_card.get("discovery", {})
    agent_slug = agent_card['agent_slug']

    print("=" * 60)
    print("TAP Agent Registration")
    print("=" * 60)
    print(f"Registry URL: {COGNEE_REGISTRY_URL}")
    print(f"Agent Slug:   {agent_slug}")
    print(f"Version:      {agent_card['version']}")
    print(f"Tier:         {discovery.get('tier', 'tertiary')}")
    print(f"Is Public:    {discovery.get('is_public', True)}")
    print(f"Is Active:    {discovery.get('is_active', True)}")
    print("=" * 60)

    # Step 1: Check for existing registration to preserve billing data
    print("\n[Step 1] Checking for existing registration...")
    existing = get_existing_agent(agent_slug, creds)

    # Step 2: Use explicit CLI pricing (no defaults allowed)
    print("\n[Step 2] Using explicit pricing and ownership from CLI...")
    if existing:
        print("  [INFO] Existing registration found - will be updated")
    else:
        print("  [INFO] New registration")

    print(f"  Owner Org:     {owner_org_id}")
    print(f"  Owner User:    {owner_user_id}")
    print(f"  Tier:          {tier}")
    print(f"  Input COGS:    {input_cogs} nanodollars/token")
    print(f"  Input Margin:  {input_margin} nanodollars/token")
    print(f"  Output COGS:   {output_cogs} nanodollars/token")
    print(f"  Output Margin: {output_margin} nanodollars/token")

    # Prepare request with all billing fields
    print("\n[Step 3] Building request body...")
    request_body = {
        "agent_slug": agent_slug,
        "agent_card": agent_card,
        # Ownership - REQUIRED
        "owner_org_id": owner_org_id,
        "owner_user_id": owner_user_id,
        # Pricing - REQUIRED, explicit from CLI
        "input_agent_cogs_per_token_nanodollars": input_cogs,
        "input_agent_margin_per_token_nanodollars": input_margin,
        "output_agent_cogs_per_token_nanodollars": output_cogs,
        "output_agent_margin_per_token_nanodollars": output_margin,
        # Best practices
        "visibility": "public",
        "agent_type": agent_card.get("agent_type", "sma"),
        "tier": tier,
    }

    # DRY RUN: Print payload without sending
    if dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN - Would send this payload:")
        print("=" * 60)
        print(json.dumps(request_body, indent=2, default=str))
        print("=" * 60)
        print("\nTo actually register, remove --dry-run flag.")
        return {"status": "dry_run", "payload": request_body}

    # Get auth headers - use TAP user auth
    headers = get_tap_auth_headers(creds)

    # Also include GCP ID token for service-to-service auth (some environments)
    id_token = get_identity_token(COGNEE_REGISTRY_URL)
    if id_token:
        headers["X-GCP-ID-Token"] = id_token

    try:
        # IMPORTANT: Always use POST to /agents/index
        # The endpoint handles upsert via ON CONFLICT - no PUT endpoint exists.
        # If you get a 409, it means the upsert failed for a data reason, not because
        # you need to switch to PUT.
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
            # 409 Conflict means the upsert ON CONFLICT clause encountered an issue.
            # This is NOT a "use PUT instead" signal - there is no PUT endpoint.
            # Check the error message for the actual issue (e.g., constraint violation).
            print(f"\n[ERROR] Registration conflict (409): {response.text[:500]}")
            print("        This usually means a data constraint issue, not a missing update.")
            print("        Check that all required fields are correct and try again.")
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


def verify_registration(agent_slug: str, creds: dict) -> bool:
    """
    Verify the agent is registered and searchable.

    This performs two checks:
    1. Direct lookup to verify agent card data
    2. Semantic search to verify indexing

    Args:
        agent_slug: The agent's unique identifier
        creds: TAP authentication credentials
    """
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # Use TAP user auth
    headers = get_tap_auth_headers(creds)

    # Also include GCP ID token for service-to-service auth
    id_token = get_identity_token(COGNEE_REGISTRY_URL)
    if id_token:
        headers["X-GCP-ID-Token"] = id_token

    # Step 1: Direct lookup to verify agent card
    print("\n[Step 1] Verifying agent card...")
    try:
        response = httpx.get(
            f"{COGNEE_REGISTRY_URL}/agents/{agent_slug}",
            headers=headers,
            timeout=30.0
        )

        if response.status_code == 200:
            data = response.json()
            card = data.get("agent_card", {})
            print(f"  [OK] Agent found in registry")
            print(f"    Display Name:     {card.get('displayName', card.get('display_name', 'N/A'))}")
            print(f"    Protocol Version: {card.get('protocolVersion', 'N/A')}")
            print(f"    Skills:           {len(card.get('skills', []))} defined")
            print(f"    Tags:             {card.get('tags', [])}")
            print(f"    URL:              {card.get('url', 'N/A')}")
        elif response.status_code == 404:
            print(f"  [ERROR] Agent not found in registry")
            return False
        else:
            print(f"  [WARN] Could not verify agent card: {response.status_code}")
    except Exception as e:
        print(f"  [WARN] Could not verify agent card: {e}")

    # Step 2: Semantic search to verify indexing
    print("\n[Step 2] Verifying semantic search indexing...")
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
                    print(f"  [OK] Agent found in search results")
                    print(f"    Relevance Score: {r.get('relevance_score', 'N/A')}")
                    return True

            print(f"  [WARN] Agent '{agent_slug}' not found in search results")
            print(f"         (This may be normal - embeddings can take time to index)")
            return False
        else:
            print(f"  [ERROR] Search failed: {response.status_code}")
            return False

    except Exception as e:
        print(f"  [ERROR] Verification failed: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Register TAP agent with Cognee Registry"
    )

    # Authentication commands
    parser.add_argument(
        "--login",
        action="store_true",
        help="Login to TAP platform (credentials cached in ~/.tap/)"
    )
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Clear cached TAP credentials"
    )

    # Registration arguments
    parser.add_argument(
        "--cloud-run-url",
        type=str,
        help="Cloud Run service URL (REQUIRED for registration)"
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip verification step"
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
    parser.add_argument(
        "--owner-org-id",
        type=str,
        default=os.getenv("TAP_OWNER_ORG_ID"),
        help="Owner organization UUID (env: TAP_OWNER_ORG_ID)"
    )
    parser.add_argument(
        "--owner-user-id",
        type=str,
        default=os.getenv("TAP_OWNER_USER_ID"),
        help="Owner user UUID (env: TAP_OWNER_USER_ID)"
    )
    # Pricing CLI arguments - REQUIRED, but can fall back to environment variables
    # Precedence: CLI arg > env var > error
    parser.add_argument(
        "--input-cogs",
        type=int,
        default=_get_env_int("TAP_INPUT_COGS_NANODOLLARS"),
        help="Input COGS per token in nanodollars (env: TAP_INPUT_COGS_NANODOLLARS)"
    )
    parser.add_argument(
        "--input-margin",
        type=int,
        default=_get_env_int("TAP_INPUT_MARGIN_NANODOLLARS"),
        help="Input margin per token in nanodollars (env: TAP_INPUT_MARGIN_NANODOLLARS)"
    )
    parser.add_argument(
        "--output-cogs",
        type=int,
        default=_get_env_int("TAP_OUTPUT_COGS_NANODOLLARS"),
        help="Output COGS per token in nanodollars (env: TAP_OUTPUT_COGS_NANODOLLARS)"
    )
    parser.add_argument(
        "--output-margin",
        type=int,
        default=_get_env_int("TAP_OUTPUT_MARGIN_NANODOLLARS"),
        help="Output margin per token in nanodollars (env: TAP_OUTPUT_MARGIN_NANODOLLARS)"
    )

    args = parser.parse_args()

    # Handle authentication commands first (before checking other requirements)
    if args.logout:
        clear_credentials()
        sys.exit(0)

    if args.login:
        try:
            creds = login_interactive()
            save_credentials(creds)
            print("\n[SUCCESS] You are now logged in. You can run registration commands.")
            sys.exit(0)
        except TAPAuthError as e:
            print(f"\n[ERROR] Login failed: {e}")
            sys.exit(1)

    # For registration, require cloud-run-url
    if not args.cloud_run_url:
        parser.error("--cloud-run-url is required for registration")

    # AUTHENTICATION REQUIRED for registration
    print("[INFO] Checking TAP authentication...")
    try:
        creds = ensure_authenticated()
    except TAPAuthError as e:
        print(f"\n[ERROR] Authentication failed: {e}")
        print("\nRun 'python register_agent.py --login' to authenticate first.")
        sys.exit(1)

    # Validate required environment variables (lazy - only when actually registering)
    validate_required_urls()

    # FAIL-FAST VALIDATION: All 6 billing fields are REQUIRED
    missing = []
    if not args.owner_org_id:
        missing.append("--owner-org-id")
    if not args.owner_user_id:
        missing.append("--owner-user-id")
    if args.input_cogs is None:
        missing.append("--input-cogs")
    if args.input_margin is None:
        missing.append("--input-margin")
    if args.output_cogs is None:
        missing.append("--output-cogs")
    if args.output_margin is None:
        missing.append("--output-margin")

    if missing:
        print("=" * 60)
        print("ERROR: The following fields are REQUIRED for registration:")
        print("=" * 60)
        for field in missing:
            print(f"  - {field}")
        print("\nAll billing fields are REQUIRED. Provide via CLI or environment:")
        print("")
        print("  Environment Variables (set in .env or shell):")
        print("    TAP_OWNER_ORG_ID        - Owner organization UUID")
        print("    TAP_OWNER_USER_ID       - Owner user UUID")
        print("    TAP_INPUT_COGS_NANODOLLARS   - Input COGS (nanodollars/token)")
        print("    TAP_INPUT_MARGIN_NANODOLLARS - Input margin (nanodollars/token)")
        print("    TAP_OUTPUT_COGS_NANODOLLARS  - Output COGS (nanodollars/token)")
        print("    TAP_OUTPUT_MARGIN_NANODOLLARS - Output margin (nanodollars/token)")
        print("")
        print("  Or via CLI (overrides env vars):")
        print("    python register_agent.py \\")
        print("      --cloud-run-url https://your-agent-xxx.run.app \\")
        print("      --owner-org-id <your-org-uuid> \\")
        print("      --owner-user-id <your-user-uuid> \\")
        print("      --input-cogs 0 \\")
        print("      --input-margin 10000 \\")
        print("      --output-cogs 0 \\")
        print("      --output-margin 12000 \\")
        print("      --tier tertiary")
        print("")
        print("  Tip: Source your .env file first:")
        print("    source deploy/.env && python scripts/register_agent.py --cloud-run-url ...")
        sys.exit(1)

    # Load manifest
    try:
        manifest = load_manifest()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # Get Cloud Run URL from args or environment (REQUIRED)
    cloud_run_url = args.cloud_run_url or os.getenv("CLOUD_RUN_URL")

    if not cloud_run_url:
        print("[ERROR] Cloud Run URL is required.")
        print("\nProvide:")
        print("  --cloud-run-url https://my-agent-xxx.run.app")
        print("\nOr set environment variable:")
        print("  CLOUD_RUN_URL")
        sys.exit(1)

    # Build agent card
    agent_card = build_agent_card(manifest, cloud_run_url)

    # Override tier from CLI if provided
    if args.tier:
        agent_card["discovery"]["tier"] = args.tier

    # Validate agent card before registration
    validation_errors = validate_agent_card(agent_card)
    if validation_errors:
        print("\n[ERROR] Agent card validation failed:")
        for error in validation_errors:
            print(f"  - {error}")
        print("\nPlease fix these issues in tap-agent.yaml and try again.")
        sys.exit(1)

    # Register with all required fields
    result = register_with_cognee(
        agent_card=agent_card,
        owner_org_id=args.owner_org_id,
        owner_user_id=args.owner_user_id,
        input_cogs=args.input_cogs,
        input_margin=args.input_margin,
        output_cogs=args.output_cogs,
        output_margin=args.output_margin,
        creds=creds,  # TAP authentication
        tier=args.tier or agent_card.get("discovery", {}).get("tier", "tertiary"),
        dry_run=args.dry_run,
    )

    # Handle dry run result
    if result.get("status") == "dry_run":
        print("\nDry run complete. No changes made.")
        sys.exit(0)

    if "error" not in result:
        # Verify Cognee registration
        if not args.skip_verify:
            verify_registration(agent_card["agent_slug"], creds)

        print("\n" + "=" * 60)
        print("Registration Complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Test discovery via Master Agent:")
        print(f'   "Find me an agent that can {agent_card["capabilities"]["primary"][0] if agent_card["capabilities"]["primary"] else "help"}"')
        print("\n2. Verify in Cognee directly:")
        print(f"   curl {COGNEE_REGISTRY_URL}/agents/{agent_card['agent_slug']}")
        print("\n3. Test via TAP UI")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
