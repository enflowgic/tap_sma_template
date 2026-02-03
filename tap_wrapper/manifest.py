"""
TAP Wrapper - System Manifest Loading and Validation

Loads the system-manifest.yaml file that describes the agent architecture
for understanding personalization and configuration.

The manifest is developer-facing and describes:
- System metadata (name, purpose, capabilities)
- Agent architecture (workflow phases, agent hierarchy)
- State schema (global preferences, per-agent preferences)
- Customization points for wrapper platforms

Schema aligns with real-world SMA implementations like Proof-Reader.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# PYDANTIC MODELS FOR MANIFEST SCHEMA (Aligned with real-world SMAs)
# =============================================================================

class SystemInfo(BaseModel):
    """Top-level system metadata."""
    name: str = ""
    version: str = "1.0.0"
    purpose: str = ""
    value_proposition: str = ""
    target_users: List[str] = Field(default_factory=list)
    key_capabilities: Dict[str, Any] = Field(default_factory=dict)
    reasoning_context: str = ""


class WorkflowPhase(BaseModel):
    """A single workflow phase in the architecture."""
    phase_id: int = 0
    name: str = ""
    agent: str = ""
    agent_type: str = "LlmAgent"
    description: str = ""
    skip_condition: Optional[str] = None
    outputs_to_state: List[str] = Field(default_factory=list)
    reasoning_context: str = ""


class Architecture(BaseModel):
    """Architecture section describing workflow and execution model."""
    cognitive_model: str = ""
    edit_pattern: str = ""
    edit_pattern_description: str = ""
    edit_strategy: str = ""
    edit_strategy_description: str = ""
    workflow_phases: List[WorkflowPhase] = Field(default_factory=list)


class AgentPreference(BaseModel):
    """Per-agent preference configuration in state_schema."""
    domain: str = ""
    description: str = ""
    example_feedback: str = ""
    wrapper_guidance: str = ""


class GlobalPreference(BaseModel):
    """Global preference in state_schema (like style_guide)."""
    type: str = "string"
    enum: List[str] = Field(default_factory=list)
    default: str = ""
    description: str = ""
    reasoning_context: str = ""
    wrapper_guidance: str = ""
    examples: List[str] = Field(default_factory=list)


class StateSchema(BaseModel):
    """State schema section with global and per-agent preferences."""
    global_preferences: Dict[str, GlobalPreference] = Field(default_factory=dict)
    per_agent_preferences: Dict[str, AgentPreference] = Field(default_factory=dict)


class AgentDefinition(BaseModel):
    """Agent definition in the agents section."""
    name: str = ""
    type: str = "LlmAgent"
    description: str = ""
    tools: List[str] = Field(default_factory=list)
    temperature: float = 0.7
    customization_points: List[str] = Field(default_factory=list)
    focus_areas: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)


class IntegrationStep(BaseModel):
    """A step in the invocation sequence."""
    step: int = 0
    action: str = ""
    timing: str = ""
    keys_to_set: List[str] = Field(default_factory=list)


class Integration(BaseModel):
    """Integration protocol section."""
    invocation_sequence: List[IntegrationStep] = Field(default_factory=list)
    state_injection_pattern: Dict[str, str] = Field(default_factory=dict)
    output_artifacts: Dict[str, Any] = Field(default_factory=dict)


class Personalization(BaseModel):
    """Personalization configuration (TAP wrapper specific)."""
    enabled: bool = True
    user_preferences_key: str = "sma_interaction_preferences"
    fallback_snippet: str = "Proceed with default professional behavior."
    debug_logging: bool = False
    # State keys where preferences are stored (aligns with state_schema.per_agent_preferences)
    preference_keys: List[str] = Field(default_factory=list)


class SystemManifest(BaseModel):
    """
    Complete system manifest schema.

    Supports both simple templates and complex multi-agent systems like Proof-Reader.
    """
    # Simple format (for basic agents)
    apiVersion: str = "tap/v1"
    kind: str = "SystemManifest"

    # Rich format (aligned with real-world SMAs)
    system: SystemInfo = Field(default_factory=SystemInfo)
    architecture: Architecture = Field(default_factory=Architecture)
    agents: Dict[str, Any] = Field(default_factory=dict)  # Flexible agent definitions
    state_schema: StateSchema = Field(default_factory=StateSchema)
    customization_guide: Dict[str, Any] = Field(default_factory=dict)
    tools: Dict[str, Any] = Field(default_factory=dict)
    integration: Integration = Field(default_factory=Integration)
    error_handling: Dict[str, Any] = Field(default_factory=dict)
    template_variables: Dict[str, Any] = Field(default_factory=dict)

    # TAP wrapper specific
    personalization: Personalization = Field(default_factory=Personalization)

    # Legacy format support (for simple manifests)
    sub_agents: List[Dict[str, Any]] = Field(default_factory=list)
    mechanics: Dict[str, Any] = Field(default_factory=dict)

    def get_preference_keys(self) -> List[str]:
        """
        Get all preference state keys that should be injected.

        Checks:
        1. state_schema.per_agent_preferences keys
        2. personalization.preference_keys
        3. Legacy sub_agents with state_key
        """
        keys = set()

        # From state_schema (real-world pattern)
        for key in self.state_schema.per_agent_preferences.keys():
            keys.add(key)

        # From personalization config
        for key in self.personalization.preference_keys:
            keys.add(key)

        # Legacy sub_agents format
        for sa in self.sub_agents:
            if sa.get("state_key"):
                keys.add(sa["state_key"])

        return list(keys)

    def get_agents_needing_personalization(self) -> List[Dict[str, Any]]:
        """
        Return agent configs that have customization_points or preferences.

        Supports both legacy sub_agents format and new state_schema format.
        """
        agents = []

        # Legacy format
        for sa in self.sub_agents:
            if sa.get("relevant_preferences") or sa.get("customization_points"):
                agents.append(sa)

        # New format from state_schema
        for key, pref in self.state_schema.per_agent_preferences.items():
            agents.append({
                "name": key.replace("_user_preferences", "").replace("_", " ").title(),
                "state_key": key,
                "description": pref.description,
                "domain": pref.domain,
                "wrapper_guidance": pref.wrapper_guidance,
            })

        return agents

    def is_simple_agent(self) -> bool:
        """Check if this is a simple single-agent (not multi-agent workflow)."""
        return (
            not self.architecture.workflow_phases and
            not self.agents and
            len(self.sub_agents) <= 1
        )


# =============================================================================
# MANIFEST LOADING (with caching)
# =============================================================================

# Module-level cache for loaded manifests
# Key: resolved manifest path, Value: (SystemManifest, file_mtime)
_manifest_cache: Dict[Path, tuple[SystemManifest, float]] = {}


def _get_default_manifest_path() -> Path:
    """Get the default manifest path based on current file location."""
    current_file = Path(__file__)
    agent_dir = current_file.parent.parent / "agent"
    if not agent_dir.exists():
        agent_dir = current_file.parent.parent.parent / "agent"

    # Try both naming conventions (hyphen preferred)
    manifest_path = agent_dir / "system-manifest.yaml"
    if not manifest_path.exists():
        manifest_path = agent_dir / "system_manifest.yaml"

    return manifest_path


def clear_manifest_cache() -> None:
    """Clear the manifest cache. Useful for testing or hot-reload scenarios."""
    _manifest_cache.clear()
    logger.debug("Manifest cache cleared")


def load_system_manifest(
    agent_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    use_cache: bool = True,
    strict: Optional[bool] = None,
) -> SystemManifest:
    """
    Load system manifest from agent/system-manifest.yaml.

    By default, uses lenient validation - warns on errors but returns empty
    manifest rather than failing. This ensures the agent can still run without
    personalization if the manifest is invalid.

    File Naming Convention:
        Preferred: system-manifest.yaml (kebab-case, matches A2A conventions)
        Legacy:    system_manifest.yaml (snake_case, supported for backwards compat)

    CACHING: By default, manifests are cached in memory. The cache is keyed by
    the resolved file path. Cache is invalidated if the file's mtime changes.
    Pass use_cache=False to bypass the cache (useful for testing).

    Args:
        agent_dir: Directory containing agent code (looks for system-manifest.yaml)
        manifest_path: Direct path to manifest file (overrides agent_dir)
        use_cache: Whether to use the in-memory cache (default: True)
        strict: If True, raise exceptions on validation errors.
                Defaults to TAP_MANIFEST_STRICT env var or False.

    Returns:
        SystemManifest instance (empty if file not found or invalid)

    Raises:
        ValueError: If strict=True and manifest validation fails
    """
    # Determine strict mode
    if strict is None:
        strict = os.environ.get("TAP_MANIFEST_STRICT", "").lower() == "true"
    # Determine manifest path
    if manifest_path is None:
        if agent_dir is None:
            manifest_path = _get_default_manifest_path()
        else:
            # Try both naming conventions (hyphen preferred)
            manifest_path = agent_dir / "system-manifest.yaml"
            if not manifest_path.exists():
                manifest_path = agent_dir / "system_manifest.yaml"

    # Resolve to absolute path for consistent cache key
    manifest_path = manifest_path.resolve()

    # Check if manifest exists
    if not manifest_path.exists():
        logger.debug(f"No system-manifest.yaml found at {manifest_path}")
        return SystemManifest()

    # Get file modification time for cache invalidation
    try:
        file_mtime = manifest_path.stat().st_mtime
    except OSError:
        file_mtime = 0.0

    # Check cache (if enabled)
    if use_cache and manifest_path in _manifest_cache:
        cached_manifest, cached_mtime = _manifest_cache[manifest_path]
        if cached_mtime == file_mtime:
            logger.debug(f"Returning cached manifest for {manifest_path}")
            return cached_manifest
        else:
            logger.debug(f"Manifest cache invalidated (file changed): {manifest_path}")

    # Load and parse YAML
    try:
        with open(manifest_path, encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        if strict:
            raise ValueError(f"Failed to parse system-manifest.yaml: {e}") from e
        logger.warning(f"Failed to parse system-manifest.yaml: {e}")
        return SystemManifest()
    except Exception as e:
        if strict:
            raise ValueError(f"Failed to load system-manifest.yaml: {e}") from e
        logger.warning(f"Failed to load system-manifest.yaml: {e}")
        return SystemManifest()

    # Validate with Pydantic (lenient by default, strict if requested)
    try:
        manifest = SystemManifest(**raw_data)
        name = manifest.system.name or manifest.apiVersion
        logger.info(f"Loaded system manifest: {name}")

        # Cache the result
        if use_cache:
            _manifest_cache[manifest_path] = (manifest, file_mtime)

        return manifest
    except Exception as e:
        if strict:
            raise ValueError(f"Invalid system-manifest.yaml: {e}") from e
        logger.warning(f"Invalid system-manifest.yaml schema: {e}")
        # Try to return partial manifest
        try:
            partial = SystemManifest(**{k: v for k, v in raw_data.items() if k in SystemManifest.model_fields})
            if use_cache:
                _manifest_cache[manifest_path] = (partial, file_mtime)
            return partial
        except Exception:
            return SystemManifest()


def load_manifest_dict(
    agent_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Load system manifest as raw dictionary.

    Useful for advanced templating or when you need the raw data
    without Pydantic validation.

    Args:
        agent_dir: Directory containing agent code
        manifest_path: Direct path to manifest file

    Returns:
        Raw manifest dictionary (empty dict if not found)
    """
    if manifest_path is None:
        if agent_dir is None:
            current_file = Path(__file__)
            agent_dir = current_file.parent.parent / "agent"

        # Try both naming conventions
        manifest_path = agent_dir / "system-manifest.yaml"
        if not manifest_path.exists():
            manifest_path = agent_dir / "system_manifest.yaml"

    if not manifest_path.exists():
        return {}

    try:
        with open(manifest_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load manifest dict: {e}")
        return {}


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Models
    "SystemManifest",
    "SystemInfo",
    "Architecture",
    "WorkflowPhase",
    "StateSchema",
    "AgentPreference",
    "GlobalPreference",
    "AgentDefinition",
    "Integration",
    "Personalization",
    # Loading functions
    "load_system_manifest",
    "load_manifest_dict",
    # Cache management
    "clear_manifest_cache",
]
