#!/bin/bash
set -e

# Create data directories if they don't exist
mkdir -p /data/autocoder /data/claude /data/projects

# Create symlinks for data directories
# This allows the app to use standard paths while data persists in /data

# Link ~/.autocoder to /data/autocoder (for registry.db)
if [ ! -L /root/.autocoder ]; then
    rm -rf /root/.autocoder
    ln -s /data/autocoder /root/.autocoder
fi

# Link ~/.claude to /data/claude (for Claude CLI credentials)
if [ ! -L /root/.claude ]; then
    rm -rf /root/.claude
    ln -s /data/claude /root/.claude
fi

# Configure git user for beads operations (required for commits)
git config --global user.email "docker@autocoder.local"
git config --global user.name "AutoCoder Docker"

# Check for authentication
if [ -z "$ANTHROPIC_API_KEY" ] && [ ! -f /data/claude/.credentials.json ]; then
    echo "=========================================="
    echo "WARNING: No authentication configured."
    echo ""
    echo "Either:"
    echo "  1. Set ANTHROPIC_API_KEY environment variable"
    echo "  2. Mount Claude credentials to /data/claude/.credentials.json"
    echo ""
    echo "The server will start but agent features won't work."
    echo "=========================================="
    echo ""
fi

# Verify beads CLI is available
if ! command -v bd &> /dev/null; then
    echo "WARNING: beads CLI (bd) not found in PATH"
fi

# Verify Claude CLI is available
if ! command -v claude &> /dev/null; then
    echo "WARNING: Claude CLI not found in PATH"
fi

# Set default environment for Docker
export ALLOW_EXTERNAL_ACCESS=${ALLOW_EXTERNAL_ACCESS:-true}
export CORS_ORIGINS=${CORS_ORIGINS:-*}
export AUTOCODER_DATA_DIR=/data
export HOST=${HOST:-0.0.0.0}
export PORT=${PORT:-8888}

echo "Starting AutoCoder on http://${HOST}:${PORT}"
echo "Data directory: /data"
echo "Projects directory: /data/projects"
echo ""

# Execute the command
exec "$@"
