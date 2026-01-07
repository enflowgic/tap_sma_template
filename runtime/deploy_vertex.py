"""
TAP Template Agent - Vertex AI Deployment Script

Deploys your agent to Vertex AI Reasoning Engine and registers
the A2A Agent Card with the TAP Gateway.

Prerequisites:
    1. Google Cloud SDK installed and authenticated
    2. Vertex AI API enabled in your project
    3. Staging bucket created:
       gsutil mb -l us-central1 gs://YOUR_PROJECT-tap-staging
    4. AI Platform service agent has bucket access:
       PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT --format="value(projectNumber)")
       gsutil iam ch serviceAccount:service-$PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com:roles/storage.objectAdmin gs://YOUR_BUCKET
    5. tap-core package installed locally (will be bundled)

Usage:
    python deploy_vertex.py              # Deploy new agent
    python deploy_vertex.py --update     # Update existing agent
    python deploy_vertex.py --delete     # Delete deployed agent
    python deploy_vertex.py --validate   # Validate agent card only
"""

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

# =============================================================================
# ENVIRONMENT SETUP
# =============================================================================

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "your-project-id")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", f"gs://{PROJECT_ID}-tap-staging")

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# HELPERS
# =============================================================================

def get_requirements() -> list[str]:
    """Load requirements, filtering out private packages to bundle."""
    req_file = Path(__file__).parent / "requirements.txt"
    requirements = []
    bundled_packages = {"tap-core", "tap_core"}

    if req_file.exists():
        with open(req_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                pkg_name = line.split(">=")[0].split("==")[0].split("[")[0].strip()
                if pkg_name.lower().replace("-", "_") in {p.lower().replace("-", "_") for p in bundled_packages}:
                    print(f"[INFO] Skipping {pkg_name} (will bundle as extra_package)")
                    continue
                requirements.append(line)

    return requirements


def validate_agent_card() -> bool:
    """Validate A2A Agent Card before deployment."""
    try:
        from agent import AGENT_CARD

        print("\n" + "=" * 60)
        print("A2A AGENT CARD VALIDATION")
        print("=" * 60)
        print(f"Agent Name: {AGENT_CARD.name}")
        print(f"Display Name: {AGENT_CARD.displayName}")
        print(f"Version: {AGENT_CARD.version}")

        if AGENT_CARD.provider:
            print(f"Provider: {AGENT_CARD.provider.organization}")

        print(f"\nSkills ({len(AGENT_CARD.skills)}):")
        for skill in AGENT_CARD.skills:
            print(f"  - {skill.id}: {skill.name}")

        if AGENT_CARD.pricing:
            print(f"\nPricing: ${AGENT_CARD.pricing.sales_price_per_1k_tokens} per 1K tokens")

        print("\n[OK] Agent card loaded successfully")
        return True

    except ImportError as e:
        print(f"\n[ERROR] Failed to import agent card: {e}")
        print("Make sure agent/agent_card.py exists.")
        sys.exit(1)


async def register_agent_card(resource_name: str) -> bool:
    """Register A2A Agent Card with TAP Gateway and Cognee."""
    gateway_url = os.environ.get("TAP_GATEWAY_URL")
    cognee_url = os.environ.get("TAP_COGNEE_URL")
    developer_token = os.environ.get("TAP_DEVELOPER_TOKEN")

    if not gateway_url and not cognee_url:
        print("\n[SKIP] TAP_GATEWAY_URL/TAP_COGNEE_URL not set")
        return False

    try:
        import httpx
        from agent import AGENT_CARD

        print("\n" + "=" * 60)
        print("REGISTERING A2A AGENT CARD")
        print("=" * 60)

        card_data = AGENT_CARD.model_dump(mode="json", exclude_none=True)
        card_data["vertexResourceName"] = resource_name

        success = False

        async with httpx.AsyncClient() as client:
            if gateway_url:
                print(f"\n[1/2] Gateway: {gateway_url}")
                headers = {"Content-Type": "application/json"}
                if developer_token:
                    headers["Authorization"] = f"Bearer {developer_token}"

                try:
                    response = await client.post(
                        f"{gateway_url}/a2a/v1/registry/agents",
                        json={"agent_card": card_data},
                        headers=headers,
                        timeout=30.0,
                    )
                    if response.status_code == 200:
                        print(f"  [OK] Gateway registration successful")
                        success = True
                    else:
                        print(f"  [WARN] Gateway: {response.status_code}")
                except Exception as e:
                    print(f"  [WARN] Gateway error: {e}")

            if cognee_url:
                print(f"\n[2/2] Cognee: {cognee_url}")
                headers = {"Content-Type": "application/json"}
                if developer_token:
                    headers["Authorization"] = f"Bearer {developer_token}"

                try:
                    response = await client.post(
                        f"{cognee_url}/agents/index",
                        json={"agent_slug": AGENT_CARD.name, "agent_card": card_data},
                        headers=headers,
                        timeout=30.0,
                    )
                    if response.status_code == 200:
                        print(f"  [OK] Cognee registration successful")
                        success = True
                    else:
                        print(f"  [WARN] Cognee: {response.status_code}")
                except Exception as e:
                    print(f"  [WARN] Cognee error: {e}")

        return success

    except ImportError:
        print("\n[SKIP] httpx not installed")
        return False


# =============================================================================
# DEPLOYMENT
# =============================================================================

def deploy_agent(skip_registration: bool = False):
    """Deploy agent to Vertex AI Reasoning Engine."""
    from vertexai import init as vertexai_init
    from vertexai.preview import reasoning_engines

    from agent import root_agent, AGENT_NAME, AGENT_METADATA

    validate_agent_card()

    print("\n" + "=" * 60)
    print(f"Deploying {AGENT_NAME} to Vertex AI")
    print("=" * 60)
    print(f"Project: {PROJECT_ID}")
    print(f"Location: {LOCATION}")
    print(f"Staging: {STAGING_BUCKET}")

    vertexai_init(
        project=PROJECT_ID,
        location=LOCATION,
        staging_bucket=STAGING_BUCKET,
    )

    requirements = get_requirements()
    print(f"\nDependencies: {len(requirements)} packages")

    # Prepare paths
    deploy_dir = Path(__file__).parent.absolute()
    agent_root = deploy_dir.parent
    original_dir = os.getcwd()

    # Copy agent package into deploy directory
    agent_src = agent_root / "agent"
    agent_dst = deploy_dir / "agent"

    if agent_dst.exists():
        shutil.rmtree(agent_dst)

    print(f"\n[INFO] Copying agent package...")
    shutil.copytree(
        agent_src,
        agent_dst,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo')
    )

    # Find tap_core to bundle
    tap_core_path = None
    try:
        import tap_core
        tap_core_path = os.path.dirname(tap_core.__file__)
        print(f"[INFO] Including tap_core from: {tap_core_path}")
    except ImportError:
        print("[WARN] tap_core not installed")

    extra_packages = ["./agent"]
    if tap_core_path:
        extra_packages.append(tap_core_path)

    print("\nCreating Reasoning Engine application...")
    print("This may take 5-10 minutes...\n")

    try:
        os.chdir(deploy_dir)

        app = reasoning_engines.ReasoningEngine.create(
            reasoning_engine=root_agent,
            display_name=AGENT_NAME,
            description=AGENT_METADATA.get("description", "TAP Agent"),
            requirements=requirements,
            extra_packages=extra_packages,
        )

        os.chdir(original_dir)

        # Cleanup
        if agent_dst.exists():
            shutil.rmtree(agent_dst)

        print("\n" + "=" * 60)
        print("DEPLOYMENT SUCCESSFUL!")
        print("=" * 60)
        print(f"Resource Name: {app.resource_name}")
        print(f"Display Name: {AGENT_NAME}")

        # Save deployment info
        info_file = deploy_dir / ".deployment_info"
        with open(info_file, "w") as f:
            f.write(f"resource_name={app.resource_name}\n")
            f.write(f"display_name={AGENT_NAME}\n")
            f.write(f"project={PROJECT_ID}\n")
            f.write(f"location={LOCATION}\n")

        # Register agent card
        if not skip_registration:
            asyncio.run(register_agent_card(app.resource_name))

        print("\n" + "=" * 60)
        print("NEXT STEPS")
        print("=" * 60)
        print("Test your agent:")
        print(f'  app = reasoning_engines.ReasoningEngine("{app.resource_name}")')
        print('  result = app.query(input={"task": "Hello!"})')

        return app

    except Exception as e:
        os.chdir(original_dir)
        if agent_dst.exists():
            shutil.rmtree(agent_dst)
        print(f"\n[ERROR] Deployment failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def delete_agent(skip_confirmation: bool = False):
    """Delete deployed agent."""
    from vertexai import init as vertexai_init
    from vertexai.preview import reasoning_engines

    info_file = Path(__file__).parent / ".deployment_info"

    if not info_file.exists():
        print("[ERROR] No deployment info found.")
        sys.exit(1)

    deployment_info = {}
    with open(info_file) as f:
        for line in f:
            if "=" in line:
                key, value = line.strip().split("=", 1)
                deployment_info[key] = value

    resource_name = deployment_info.get("resource_name")

    print("=" * 60)
    print("Deleting Deployed Agent")
    print("=" * 60)
    print(f"Resource: {resource_name}")

    if not skip_confirmation:
        response = input("\nDelete? (y/n): ").strip().lower()
        if response != "y":
            print("Cancelled.")
            return

    vertexai_init(project=PROJECT_ID, location=LOCATION)

    try:
        app = reasoning_engines.ReasoningEngine(resource_name)
        app.delete()
        print("\n[SUCCESS] Agent deleted.")
        info_file.unlink()
    except Exception as e:
        print(f"\n[ERROR] Deletion failed: {e}")
        sys.exit(1)


def show_status():
    """Show deployment status."""
    info_file = Path(__file__).parent / ".deployment_info"

    print("=" * 60)
    print("Deployment Status")
    print("=" * 60)

    if not info_file.exists():
        print("Status: NOT DEPLOYED")
        print("\nTo deploy: python deploy_vertex.py")
        return

    print("Status: DEPLOYED")
    with open(info_file) as f:
        for line in f:
            if "=" in line:
                key, value = line.strip().split("=", 1)
                print(f"  {key}: {value}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Deploy TAP Agent to Vertex AI")
    parser.add_argument("--update", action="store_true", help="Update existing")
    parser.add_argument("--delete", action="store_true", help="Delete agent")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--validate", action="store_true", help="Validate only")
    parser.add_argument("--skip-registration", action="store_true", help="Skip registration")

    args = parser.parse_args()

    if args.validate:
        validate_agent_card()
    elif args.status:
        show_status()
    elif args.delete:
        delete_agent()
    elif args.update:
        delete_agent(skip_confirmation=True)
        deploy_agent()
    else:
        deploy_agent(skip_registration=args.skip_registration)


if __name__ == "__main__":
    main()
