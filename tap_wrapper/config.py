"""
TAP Wrapper - Configuration from Manifest

Parses tap-agent.yaml to extract agent configuration.
Developers configure their agent via the manifest, not code.

CONFIGURATION PRECEDENCE:
    1. Environment variables (highest priority)
    2. tap-agent.yaml manifest (default values)

Environment overrides:
    - TAP_MODEL_NAME: Overrides deployment.model
    - LOG_LEVEL: Overrides deployment.env log level
    - TAP_AGENT_MANIFEST: Path to manifest file
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class ProviderConfig:
    """Provider/organization information."""
    organization: str = "developer@example.com"
    organization_name: str = "My Organization"
    support_email: Optional[str] = None
    url: Optional[str] = None


@dataclass
class SkillConfig:
    """Agent skill definition."""
    id: str
    name: str
    description: str
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)


@dataclass
class DeploymentConfig:
    """Deployment configuration."""
    runtime: str = "cloud-run"
    model: str = "gemini-3-flash-preview"
    region: str = "us-central1"
    cpu: int = 4
    memory: str = "4Gi"
    timeout_seconds: int = 120
    max_instances: int = 10


@dataclass
class AgentConfig:
    """
    Agent configuration parsed from tap-agent.yaml.

    This is the single source of truth for agent metadata.
    Developers edit the manifest, not Python code.
    """
    # Identity
    slug: str
    display_name: str
    version: str
    model: str
    description: str

    # Provider
    provider: ProviderConfig

    # Discovery
    tier: str = "tertiary"
    is_public: bool = True
    is_active: bool = True

    # Capabilities
    skills: List[SkillConfig] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # Deployment
    deployment: DeploymentConfig = field(default_factory=DeploymentConfig)

    @classmethod
    def from_manifest(cls, manifest_path: str = None) -> "AgentConfig":
        """
        Load configuration from tap-agent.yaml manifest.

        Args:
            manifest_path: Path to manifest file. If None, searches
                          standard locations.

        Returns:
            AgentConfig instance
        """
        if manifest_path is None:
            manifest_path = cls._find_manifest()

        with open(manifest_path, "r") as f:
            data = yaml.safe_load(f)

        return cls._parse_manifest(data)

    @staticmethod
    def _find_manifest() -> str:
        """Find tap-agent.yaml in standard locations."""
        # Check environment variable first
        if env_path := os.environ.get("TAP_AGENT_MANIFEST"):
            if Path(env_path).exists():
                return env_path

        # Search relative to this file
        base_paths = [
            Path(__file__).parent.parent,  # tap_template_agent/
            Path.cwd(),                      # Current directory
            Path.cwd().parent,               # Parent directory
        ]

        for base in base_paths:
            manifest_path = base / "tap-agent.yaml"
            if manifest_path.exists():
                return str(manifest_path)

        raise FileNotFoundError(
            "tap-agent.yaml not found. Ensure it exists in the project root "
            "or set TAP_AGENT_MANIFEST environment variable."
        )

    @classmethod
    def _parse_manifest(cls, data: Dict[str, Any]) -> "AgentConfig":
        """Parse manifest dictionary into AgentConfig."""
        metadata = data.get("metadata", {})
        provider_data = data.get("provider", {})
        discovery = data.get("discovery", {})
        deployment_data = data.get("deployment", {})
        resources = deployment_data.get("resources", {})
        skills_data = data.get("skills", [])

        # Parse provider
        provider = ProviderConfig(
            organization=provider_data.get("organization", "developer@example.com"),
            organization_name=provider_data.get("organization_name", "My Organization"),
            support_email=provider_data.get("support_email"),
            url=provider_data.get("url"),
        )

        # Parse deployment with environment overrides
        # TAP_MODEL_NAME takes precedence over manifest
        model = os.environ.get("TAP_MODEL_NAME") or deployment_data.get("model", "gemini-3-flash-preview")

        deployment = DeploymentConfig(
            runtime=deployment_data.get("runtime", "cloud-run"),
            model=model,
            region=os.environ.get("GOOGLE_CLOUD_LOCATION") or deployment_data.get("region", "us-central1"),
            cpu=resources.get("cpu", 4),
            memory=resources.get("memory", "4Gi"),
            timeout_seconds=resources.get("timeout_seconds", 120),
            max_instances=resources.get("max_instances", 10),
        )

        # Parse skills
        skills = [
            SkillConfig(
                id=s.get("id", "main-skill"),
                name=s.get("name", "Main Skill"),
                description=s.get("description", ""),
                tags=s.get("tags", []),
                examples=s.get("examples", []),
            )
            for s in skills_data
        ]

        return cls(
            slug=metadata.get("slug", "my-agent"),
            display_name=metadata.get("display_name", "My Agent"),
            version=metadata.get("version", "1.0.0"),
            model=model,  # Use the environment-aware model from deployment config
            description=metadata.get("description", "").strip(),
            provider=provider,
            tier=discovery.get("tier", "tertiary"),
            is_public=discovery.get("is_public", True),
            is_active=discovery.get("is_active", True),
            skills=skills,
            tags=data.get("tags", []),
            deployment=deployment,
        )


# Singleton config instance - loaded on first access
_config: Optional[AgentConfig] = None


def get_config() -> AgentConfig:
    """
    Get the agent configuration (singleton).

    Loads from tap-agent.yaml on first access.
    """
    global _config
    if _config is None:
        _config = AgentConfig.from_manifest()
    return _config


def reload_config(manifest_path: str = None) -> AgentConfig:
    """
    Reload configuration from manifest.

    Useful for testing or dynamic config updates.
    """
    global _config
    _config = AgentConfig.from_manifest(manifest_path)
    return _config


__all__ = [
    "AgentConfig",
    "ProviderConfig",
    "SkillConfig",
    "DeploymentConfig",
    "get_config",
    "reload_config",
]
