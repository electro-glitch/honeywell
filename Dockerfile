# ===================================================
# Eco-Loop Building Agents — Dockerfile
# Multi-stage build: slim production image
# ===================================================
FROM python:3.12-slim AS base

# System dependencies for WeasyPrint (PDF) and other libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libcairo2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Builder stage ────────────────────────────────────────────────────────────
FROM base AS builder

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# ── Final stage ───────────────────────────────────────────────────────────────
FROM base AS final

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy source code
COPY . .

# Create required directories
RUN mkdir -p \
    outputs/reports \
    outputs/plots \
    data/idf \
    data/weather

# Environment defaults (override with docker run -e or .env)
ENV SIMULATION_MODE=mock \
    LLM_MODEL=llama3 \
    OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    DATABASE_PATH=/app/data/eco_loop.db \
    LOG_LEVEL=INFO

# Expose MCP port (optional SSE mode)
EXPOSE 8765

# Default command: run baseline
ENTRYPOINT ["python", "main.py"]
CMD ["baseline", "--hours", "24"]
