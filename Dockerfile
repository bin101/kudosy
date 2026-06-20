# ──────────────────────────────────────────────────────────────────────────────
# Kudosy — multi-stage Dockerfile
# Base: python:3.13-slim (no upstream image dependency, no aexel90 reference)
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install only what's needed for building
RUN pip install --no-cache-dir --upgrade pip hatchling

# Copy project metadata first (layer cache: only invalidated when deps change)
COPY pyproject.toml README.md LICENSE ./

# Copy source
COPY src/ ./src/

# Build wheel into /build/dist/
RUN pip wheel --no-cache-dir --no-deps --wheel-dir dist .

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Metadata
LABEL org.opencontainers.image.title="Kudosy"
LABEL org.opencontainers.image.description="Automatic kudos, human-like timing"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/bin101/kudosy"

WORKDIR /app

# Runtime system deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install the wheel (no dev deps, no src)
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Data directory — mounts here in production
ENV KUDOSY_DATA_DIR=/data
VOLUME ["/data"]

# Default port
EXPOSE 8080
ENV KUDOSY_PORT=8080
ENV KUDOSY_HOST=0.0.0.0
ENV KUDOSY_LOG_LEVEL=INFO

# Non-root user for security
RUN useradd --create-home --shell /bin/bash kudosy
USER kudosy

# Health check — polls /api/status every 30s
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsSL http://localhost:${KUDOSY_PORT}/api/status > /dev/null || exit 1

CMD ["python", "-m", "kudosy"]
