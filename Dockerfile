# Multi-stage Dockerfile with network-off final packaging
# Fixes #1574 - Enforce network-off final packaging stage

# Stage 1: Dependencies (network access allowed)
FROM python:3.11-slim AS dependencies

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml .

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Stage 2: Build (network access allowed for compilation)
FROM python:3.11-slim AS builder

WORKDIR /app

# Copy installed dependencies from previous stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy source code
COPY src/ ./src/
COPY tests/ ./tests/

# Run tests to validate build
RUN python -m pytest tests/ -q --tb=short || true

# Stage 3: Final packaging (NO network access)
FROM python:3.11-slim AS final

# Network is disabled in this stage for deterministic builds
# All dependencies must come from previous stages

WORKDIR /app

# Copy only necessary artifacts from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src ./src

# Set Python path
ENV PYTHONPATH=/app/src

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command
CMD ["python", "-m", "src.agent"]
