#!/bin/bash
# Test script to build and verify the Docker container is working
# Automatically cleans up after testing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use clearly distinct test container name to avoid accidents
TEST_CONTAINER_NAME="autocoder-TEST-EPHEMERAL-$$"
TEST_DATA_DIR="$SCRIPT_DIR/.docker-test-data-$$"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "AutoCoder Docker Build & Test"
echo "========================================"
echo "Test container: $TEST_CONTAINER_NAME"
echo ""

# Cleanup function - always runs on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Cleaning up test environment...${NC}"
    docker stop "$TEST_CONTAINER_NAME" 2>/dev/null || true
    docker rm "$TEST_CONTAINER_NAME" 2>/dev/null || true
    rm -rf "$TEST_DATA_DIR" 2>/dev/null || true
    echo -e "${GREEN}Cleanup complete.${NC}"
}

# Set trap to cleanup on exit (success or failure)
trap cleanup EXIT

# Step 1: Build the image
echo -e "${YELLOW}[1/6] Building Docker image...${NC}"
docker build -t autocoder .
echo -e "${GREEN}Build successful!${NC}"
echo ""

# Step 2: Create test data directory
echo -e "${YELLOW}[2/6] Setting up test environment...${NC}"
mkdir -p "$TEST_DATA_DIR/projects"
mkdir -p "$TEST_DATA_DIR/autocoder"
mkdir -p "$TEST_DATA_DIR/claude"
echo -e "${GREEN}Test data directory created.${NC}"
echo ""

# Step 3: Load Claude credentials
echo -e "${YELLOW}[3/6] Loading Claude credentials...${NC}"
CLAUDE_CREDS="$HOME/.claude"

if [ -f "$CLAUDE_CREDS/.credentials.json" ]; then
    cp "$CLAUDE_CREDS/.credentials.json" "$TEST_DATA_DIR/claude/"
    [ -f "$CLAUDE_CREDS/settings.json" ] && cp "$CLAUDE_CREDS/settings.json" "$TEST_DATA_DIR/claude/"
    echo -e "${GREEN}Claude credentials loaded.${NC}"
else
    echo -e "${YELLOW}WARNING: No Claude credentials found at $CLAUDE_CREDS/.credentials.json${NC}"
    echo "Tests will continue but agent features won't work."
fi
echo ""

# Step 4: Start container
echo -e "${YELLOW}[4/6] Starting test container...${NC}"
docker run -d \
    --name "$TEST_CONTAINER_NAME" \
    -e ALLOW_EXTERNAL_ACCESS=true \
    -e CORS_ORIGINS="*" \
    -p 18888:8888 \
    -v "$TEST_DATA_DIR:/data" \
    autocoder

echo "Waiting for container to start..."
sleep 5
echo -e "${GREEN}Container started!${NC}"
echo ""

# Step 5: Test API endpoints
echo -e "${YELLOW}[5/6] Testing API endpoints...${NC}"

# Test health endpoint
echo -n "  Health check: "
HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:18888/api/health 2>/dev/null || echo "000")
if [ "$HEALTH_RESPONSE" = "200" ]; then
    echo -e "${GREEN}PASS${NC} (HTTP $HEALTH_RESPONSE)"
else
    echo -e "${RED}FAIL${NC} (HTTP $HEALTH_RESPONSE)"
    echo ""
    echo "Container logs:"
    docker logs "$TEST_CONTAINER_NAME"
    exit 1
fi

# Test setup status endpoint
echo -n "  Setup status: "
SETUP_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:18888/api/setup/status 2>/dev/null || echo "000")
if [ "$SETUP_RESPONSE" = "200" ]; then
    echo -e "${GREEN}PASS${NC} (HTTP $SETUP_RESPONSE)"
else
    echo -e "${RED}FAIL${NC} (HTTP $SETUP_RESPONSE)"
    exit 1
fi

# Test projects endpoint (no trailing slash)
echo -n "  Projects API: "
PROJECTS_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:18888/api/projects 2>/dev/null || echo "000")
if [ "$PROJECTS_RESPONSE" = "200" ]; then
    echo -e "${GREEN}PASS${NC} (HTTP $PROJECTS_RESPONSE)"
else
    echo -e "${RED}FAIL${NC} (HTTP $PROJECTS_RESPONSE)"
    exit 1
fi

# Test static files (React app)
echo -n "  Static files: "
INDEX_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:18888/ 2>/dev/null || echo "000")
if [ "$INDEX_RESPONSE" = "200" ]; then
    echo -e "${GREEN}PASS${NC} (HTTP $INDEX_RESPONSE)"
else
    echo -e "${RED}FAIL${NC} (HTTP $INDEX_RESPONSE)"
    exit 1
fi

echo ""

# Step 6: Verify CLI tools in container
echo -e "${YELLOW}[6/6] Verifying CLI tools in container...${NC}"

# Check beads CLI
echo -n "  beads (bd): "
if docker exec "$TEST_CONTAINER_NAME" which bd > /dev/null 2>&1; then
    BD_VERSION=$(docker exec "$TEST_CONTAINER_NAME" bd --version 2>/dev/null || echo "installed")
    echo -e "${GREEN}PASS${NC} ($BD_VERSION)"
else
    echo -e "${YELLOW}WARN${NC} (not found - may need manual install)"
fi

# Check Claude CLI
echo -n "  claude CLI: "
if docker exec "$TEST_CONTAINER_NAME" which claude > /dev/null 2>&1; then
    echo -e "${GREEN}PASS${NC}"
else
    echo -e "${YELLOW}WARN${NC} (not found)"
fi

# Check Python
echo -n "  Python: "
PYTHON_VERSION=$(docker exec "$TEST_CONTAINER_NAME" python --version 2>&1)
echo -e "${GREEN}PASS${NC} ($PYTHON_VERSION)"

# Check Node
echo -n "  Node.js: "
NODE_VERSION=$(docker exec "$TEST_CONTAINER_NAME" node --version 2>&1)
echo -e "${GREEN}PASS${NC} ($NODE_VERSION)"

# Check git
echo -n "  Git: "
GIT_VERSION=$(docker exec "$TEST_CONTAINER_NAME" git --version 2>&1)
echo -e "${GREEN}PASS${NC} ($GIT_VERSION)"

# Check Claude credentials were loaded
echo -n "  Credentials: "
if docker exec "$TEST_CONTAINER_NAME" test -f /data/claude/.credentials.json 2>/dev/null; then
    echo -e "${GREEN}PASS${NC} (loaded)"
else
    echo -e "${YELLOW}WARN${NC} (not found)"
fi

echo ""
echo "========================================"
echo -e "${GREEN}All tests passed!${NC}"
echo "========================================"
echo ""
echo "Test container will be automatically removed."
