#!/bin/bash
# Run autocoder with mounted Claude credentials from ~/.claude

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CLAUDE_CREDS="$HOME/.claude"

if [ ! -f "$CLAUDE_CREDS/.credentials.json" ]; then
    echo "Error: Claude credentials not found at $CLAUDE_CREDS/.credentials.json"
    echo ""
    echo "Run 'claude login' first to authenticate with Claude."
    exit 1
fi

# Create data directories if they don't exist
mkdir -p "$SCRIPT_DIR/data/claude"
mkdir -p "$SCRIPT_DIR/data/projects"
mkdir -p "$SCRIPT_DIR/data/autocoder"

# Copy credentials to data directory (so they persist in the volume)
echo "Copying Claude credentials to data directory..."
cp "$CLAUDE_CREDS/.credentials.json" "$SCRIPT_DIR/data/claude/"
[ -f "$CLAUDE_CREDS/settings.json" ] && cp "$CLAUDE_CREDS/settings.json" "$SCRIPT_DIR/data/claude/"

# Remove existing container if it exists
docker rm -f autocoder 2>/dev/null || true

docker run -d \
    --name autocoder \
    --restart unless-stopped \
    -e ALLOW_EXTERNAL_ACCESS=true \
    -e CORS_ORIGINS="*" \
    -p 8888:8888 \
    -v "$SCRIPT_DIR/data:/data" \
    autocoder

echo ""
echo "AutoCoder started!"
echo "  URL: http://localhost:8888"
echo "  Data: $SCRIPT_DIR/data"
echo ""
echo "Commands:"
echo "  docker logs -f autocoder    # View logs"
echo "  docker stop autocoder       # Stop container"
echo "  docker start autocoder      # Start container"
