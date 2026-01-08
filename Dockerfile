# =============================================================================
# Stage 1: Build React frontend
# =============================================================================
FROM node:22-bookworm AS frontend-builder

WORKDIR /build/ui

# Copy package files first for better caching
COPY ui/package.json ui/package-lock.json ./

# Install dependencies
RUN npm ci --no-audit

# Copy UI source and build
COPY ui/ ./
RUN npm run build


# =============================================================================
# Stage 2: Production image
# =============================================================================
FROM ubuntu:24.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    nodejs \
    npm \
    git \
    curl \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally via npm
RUN npm install -g @anthropic-ai/claude-code

# Install beads CLI (bd)
RUN curl -fsSL https://raw.githubusercontent.com/steveyegge/beads/main/scripts/install.sh | bash \
    && mv /root/.local/bin/bd /usr/local/bin/bd 2>/dev/null || true

# Set up application directory
WORKDIR /app

# Create Python virtual environment
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Copy and install Python dependencies first (for better caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy pre-built frontend from builder stage
COPY --from=frontend-builder /build/ui/dist ./ui/dist

# Create data directories
RUN mkdir -p /data/projects /data/autocoder /data/claude

# Copy and set entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Set environment variables
ENV PYTHONPATH=/app
ENV AUTOCODER_DATA_DIR=/data

# Expose port
EXPOSE 8888

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8888"]
