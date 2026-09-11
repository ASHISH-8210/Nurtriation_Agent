# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

LABEL maintainer="NutriMind Team"
LABEL description="NutriMind MCP Tools Server — IBM watsonx Orchestrate"

WORKDIR /app

# Install system dependencies for faiss-cpu
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libopenblas-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY tools/ ./tools/
COPY rag/nutrition.index ./rag/nutrition.index
COPY rag/metadata.jsonl ./rag/metadata.jsonl

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -sf -H "X-NutriMind-Key: ${MCP_SERVER_API_KEY}" http://localhost:8080/health || exit 1

# Non-root user
RUN useradd -m -u 1000 nutrimind
USER nutrimind

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "tools.nutrimind_tools:mcp.http_app", \
     "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
