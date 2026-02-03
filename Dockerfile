# =============================================================================
# TAP AGENT DOCKERFILE - Cloud Run Deployment
# =============================================================================
#
# SMAs deploy to Cloud Run because they expose A2A protocol endpoints
# (agent card, sync RPC, streaming, health checks).
#
# Build: docker build -t tap-template-agent .
# Run:   docker run -p 8080:8080 -e GOOGLE_CLOUD_PROJECT=your-project tap-template-agent
#
# =============================================================================

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY runtime/requirements.txt ./requirements.txt

# Install Python dependencies
# Note: tap-core requires Artifact Registry access - configure pip.conf if needed
RUN pip install --no-cache-dir -r requirements.txt

# Copy the agent package (your agent definition, schemas, tools)
COPY agent/ ./agent/

# Copy the runtime (A2A server and utilities)
COPY runtime/ ./runtime/

# Copy root-level entry point
COPY main.py ./main.py

# Copy configuration files
COPY tap-agent.yaml ./tap-agent.yaml

# Set environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV GOOGLE_GENAI_USE_VERTEXAI=true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Expose port
EXPOSE ${PORT}

# Run the A2A server
CMD ["python", "main.py"]
