#!/bin/bash
# Run autocoder with ANTHROPIC_API_KEY environment variable

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "Error: ANTHROPIC_API_KEY environment variable is not set"
    echo ""
    echo "Usage: ANTHROPIC_API_KEY=sk-... ./docker-run-apikey.sh"
    echo ""
    echo "Or export it first:"
    echo "  export ANTHROPIC_API_KEY=sk-..."
    echo "  ./docker-run-apikey.sh"
    exit 1
fi

# Create data directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/data"

# Remove existing container if it exists
docker rm -f autocoder 2>/dev/null || true

docker run -d \
    --name autocoder \
    --restart unless-stopped \
    -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
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
