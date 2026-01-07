# =============================================================================
# TAP AGENT DOCKERFILE
# =============================================================================
#
# This Dockerfile is used for Cloud Run deployments.
# For Vertex AI deployments, the platform handles containerization automatically.
#
# Build: docker build -t my-agent .
# Run:   docker run -p 8080:8080 my-agent
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
COPY tap-my-agent/requirements.txt ./requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the agent package
COPY my_agent/ ./my_agent/

# Copy the TAP wrapper
COPY tap-my-agent/app/ ./app/
COPY tap-my-agent/main.py ./main.py

# Copy configuration files
COPY tap-agent.yaml ./tap-agent.yaml

# Set environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Expose port
EXPOSE ${PORT}

# Run the application
# For Cloud Run, use gunicorn with uvicorn workers
CMD ["python", "main.py"]
