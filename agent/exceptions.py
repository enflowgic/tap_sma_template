"""
TAP Template Agent - Custom Exceptions

Defines exception classes for agent-specific error handling.
These exceptions enable structured error responses that the platform
can interpret and handle appropriately.
"""

from typing import List, Dict, Any


class MissingCredentialsError(Exception):
    """
    Raised when required OAuth credentials are not provided.

    Use this exception in tools that require OAuth access to third-party
    services. The platform will catch this error and prompt the user to
    connect their account or purchase one-time access.

    Example:
        from tap_core.tools import get_oauth_credentials
        from agent.exceptions import MissingCredentialsError

        def fetch_google_doc(doc_url: str) -> str:
            google_creds = get_oauth_credentials("google")
            if not google_creds:
                raise MissingCredentialsError(
                    service="Google Docs",
                    scopes=["https://www.googleapis.com/auth/documents.readonly"]
                )
            # Use credentials...
    """

    def __init__(self, service: str, scopes: List[str]):
        """
        Initialize MissingCredentialsError.

        Args:
            service: Human-readable service name (e.g., "Google Docs", "Salesforce")
            scopes: List of OAuth scopes required
        """
        self.service = service
        self.scopes = scopes
        self.error_code = "MISSING_OAUTH_CREDENTIALS"
        super().__init__(
            f"Missing OAuth credentials for {service}. "
            f"Required scopes: {', '.join(scopes)}."
        )

    def to_platform_response(self) -> Dict[str, Any]:
        """
        Format error for platform to handle.

        Returns a structured response that Gateway can interpret
        to trigger the credential flow (OAuth connect or one-time purchase).

        Returns:
            Dict with error_code, service, required_scopes, and action_required
        """
        return {
            "error_code": self.error_code,
            "service": self.service,
            "required_scopes": self.scopes,
            "action_required": "oauth_connect",
        }


class AgentExecutionError(Exception):
    """
    Generic agent execution error with structured response.

    Use for errors that should be reported back to the platform
    with additional context.
    """

    def __init__(self, message: str, error_code: str = "AGENT_ERROR", details: Dict[str, Any] = None):
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)

    def to_platform_response(self) -> Dict[str, Any]:
        """Format error for platform."""
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": self.details,
        }


__all__ = [
    "MissingCredentialsError",
    "AgentExecutionError",
]
