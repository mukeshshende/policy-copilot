# ── Policy Copilot — Dockerfile ───────────────────────────────────────────────
# AIpportunity Pvt. Ltd.
#
# Build:   docker build -t policy-copilot:latest .
# Run:     docker compose up   (preferred — mounts .env and data volumes)

FROM python:3.12-slim

# Prevent .pyc files and enable unbuffered stdout (clean container logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies needed by ChromaDB / sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer — only rebuilds on requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copy application source
# .dockerignore excludes: .venv, data/chroma_db, .env, __pycache__, .git
COPY . .

# Gradio listens on all interfaces inside the container
ENV GRADIO_PORT=7860

EXPOSE 7860

# data/chroma_db and .env are bind-mounted at runtime via docker-compose.yml
# so the container starts without them baked in.
CMD ["python", "-m", "src.app"]
