"""
TAP Template Agent - Cloud Run Entry Point

This is the main entry point for Cloud Run deployments.
It imports and runs the FastAPI A2A server from runtime/server.py.

For local development, you can also use:
- runtime/main.py      - Interactive CLI
- runtime/server.py    - Direct server execution

Usage:
    python main.py                    # Run server on PORT (default 8080)
    uvicorn main:app --reload         # Development with auto-reload
    gunicorn main:app -k uvicorn.workers.UvicornWorker  # Production
"""

import os
import sys

# =============================================================================
# PATH SETUP
# =============================================================================

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# =============================================================================
# ENVIRONMENT DEFAULTS
# =============================================================================

# Set default environment variables (can be overridden by Cloud Run config)
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

# Load .env file if present (for local development)
env_file = os.path.join(current_dir, "runtime", ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

# =============================================================================
# IMPORT APP
# =============================================================================

# Import the FastAPI app from the runtime server
# This provides:
#   - GET  /.well-known/agent.json  - A2A Agent Card discovery
#   - POST /                         - JSON-RPC 2.0 A2A endpoint (root)
#   - POST /stream                   - SSE streaming endpoint
#   - GET  /health                   - Health check for Cloud Run
#   - GET  /                         - Root info endpoint (GET only)
from runtime.server import app

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    import logging

    # Configure logging
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Get configuration from environment
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    log_level = os.environ.get("LOG_LEVEL", "info").lower()

    logger.info(f"Starting TAP Template Agent on {host}:{port}")
    logger.info(f"A2A Agent Card: http://{host}:{port}/.well-known/agent.json")
    logger.info(f"Health Check: http://{host}:{port}/health")

    # Run the server
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
    )
