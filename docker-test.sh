#!/bin/bash
# =============================================================================
# Docker Test Script for Per-Project Containers
# =============================================================================
# Tests the per-project Docker container architecture:
# 1. Builds the autocoder-project image
# 2. Starts the FastAPI server
# 3. Creates test projects and spins up containers
# 4. Verifies container isolation and functionality
# 5. Cleans up everything
#
# Usage: ./docker-test.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test configuration
TEST_PROJECT_ALPHA="docker-test-alpha-$$"
TEST_PROJECT_BETA="docker-test-beta-$$"
TEST_DIR="/tmp/autocoder-docker-test-$$"
SERVER_PORT=8765
SERVER_PID=""

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"

    # Stop and remove containers if they exist
    docker stop "autocoder-${TEST_PROJECT_ALPHA}" 2>/dev/null || true
    docker stop "autocoder-${TEST_PROJECT_BETA}" 2>/dev/null || true
    docker rm "autocoder-${TEST_PROJECT_ALPHA}" 2>/dev/null || true
    docker rm "autocoder-${TEST_PROJECT_BETA}" 2>/dev/null || true

    # Stop server
    if [ -n "$SERVER_PID" ]; then
        kill $SERVER_PID 2>/dev/null || true
        wait $SERVER_PID 2>/dev/null || true
    fi

    # Remove test directories
    rm -rf "$TEST_DIR"

    echo -e "${GREEN}Cleanup complete${NC}"
}

# Set trap for cleanup on exit
trap cleanup EXIT

# Helper functions
log_step() {
    echo -e "\n${YELLOW}=== $1 ===${NC}"
}

log_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

log_error() {
    echo -e "${RED}✗ $1${NC}"
    exit 1
}

check_command() {
    if ! command -v $1 &> /dev/null; then
        log_error "$1 is required but not installed"
    fi
}

echo "========================================"
echo "AutoCoder Per-Project Docker Test"
echo "========================================"
echo "Test projects: $TEST_PROJECT_ALPHA, $TEST_PROJECT_BETA"
echo ""

# =============================================================================
# Pre-flight checks
# =============================================================================
log_step "Pre-flight checks"

check_command docker
check_command curl
check_command python3

# Check Docker is running
if ! docker info &> /dev/null; then
    log_error "Docker is not running"
fi
log_success "Docker is running"

# Check port is available
if curl -s "http://localhost:${SERVER_PORT}" &> /dev/null; then
    log_error "Port ${SERVER_PORT} is already in use"
fi
log_success "Port ${SERVER_PORT} is available"

# =============================================================================
# Build Docker image
# =============================================================================
log_step "Building autocoder-project image"

docker build -f Dockerfile.project -t autocoder-project . || log_error "Failed to build image"
log_success "Image built successfully"

# Verify image
if ! docker image inspect autocoder-project &> /dev/null; then
    log_error "Image not found after build"
fi
log_success "Image verified"

# =============================================================================
# Start FastAPI server
# =============================================================================
log_step "Starting FastAPI server"

# Activate venv and start server
if [ -d "venv" ]; then
    source venv/bin/activate
else
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
fi

uvicorn server.main:app --host 127.0.0.1 --port $SERVER_PORT &
SERVER_PID=$!
sleep 3

# Verify server is running
if ! curl -s "http://localhost:${SERVER_PORT}/api/setup/status" | grep -q "claude_cli"; then
    log_error "Server failed to start"
fi
log_success "Server started on port ${SERVER_PORT}"

# =============================================================================
# Create test projects
# =============================================================================
log_step "Creating test projects"

mkdir -p "$TEST_DIR/$TEST_PROJECT_ALPHA" "$TEST_DIR/$TEST_PROJECT_BETA"

# Initialize git repos
for proj in "$TEST_PROJECT_ALPHA" "$TEST_PROJECT_BETA"; do
    cd "$TEST_DIR/$proj"
    git init -q
    echo "# Test Project $proj" > README.md
    git add .
    git commit -q -m "init"
done
cd "$SCRIPT_DIR"

log_success "Test directories created"

# Register projects via API
for proj in "$TEST_PROJECT_ALPHA" "$TEST_PROJECT_BETA"; do
    response=$(curl -s -X POST "http://localhost:${SERVER_PORT}/api/projects" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"$proj\", \"path\": \"$TEST_DIR/$proj\"}")

    if echo "$response" | grep -q "detail"; then
        log_error "Failed to register project $proj: $response"
    fi
done
log_success "Projects registered via API"

# =============================================================================
# Start containers and verify isolation
# =============================================================================
log_step "Starting project containers"

# Start first container
response=$(curl -s -X POST "http://localhost:${SERVER_PORT}/api/projects/${TEST_PROJECT_ALPHA}/agent/start" \
    -H "Content-Type: application/json" \
    -d '{"instruction": null}')

if ! echo "$response" | grep -q '"success":true'; then
    log_error "Failed to start container for $TEST_PROJECT_ALPHA: $response"
fi
log_success "Container started for $TEST_PROJECT_ALPHA"

# Start second container
response=$(curl -s -X POST "http://localhost:${SERVER_PORT}/api/projects/${TEST_PROJECT_BETA}/agent/start" \
    -H "Content-Type: application/json" \
    -d '{"instruction": null}')

if ! echo "$response" | grep -q '"success":true'; then
    log_error "Failed to start container for $TEST_PROJECT_BETA: $response"
fi
log_success "Container started for $TEST_PROJECT_BETA"

sleep 2

# Verify both containers are running
log_step "Verifying container isolation"

container_count=$(docker ps --filter "name=autocoder-docker-test" --format "{{.Names}}" | wc -l)
if [ "$container_count" -ne 2 ]; then
    log_error "Expected 2 containers, found $container_count"
fi
log_success "Both containers are running"

# Verify volume mounts
alpha_mount=$(docker inspect "autocoder-${TEST_PROJECT_ALPHA}" --format '{{range .Mounts}}{{if eq .Destination "/project"}}{{.Source}}{{end}}{{end}}')
beta_mount=$(docker inspect "autocoder-${TEST_PROJECT_BETA}" --format '{{range .Mounts}}{{if eq .Destination "/project"}}{{.Source}}{{end}}{{end}}')

if [ "$alpha_mount" != "$TEST_DIR/$TEST_PROJECT_ALPHA" ]; then
    log_error "Alpha container has wrong mount: $alpha_mount"
fi
if [ "$beta_mount" != "$TEST_DIR/$TEST_PROJECT_BETA" ]; then
    log_error "Beta container has wrong mount: $beta_mount"
fi
log_success "Volume mounts are correct and isolated"

# Verify Claude and beads are installed
if ! docker exec "autocoder-${TEST_PROJECT_ALPHA}" which claude &> /dev/null; then
    log_error "Claude not found in container"
fi
if ! docker exec "autocoder-${TEST_PROJECT_ALPHA}" which bd &> /dev/null; then
    log_error "Beads (bd) not found in container"
fi
log_success "Claude Code and beads CLI are available"

# =============================================================================
# Test stop and restart
# =============================================================================
log_step "Testing stop and restart"

# Stop alpha container
response=$(curl -s -X POST "http://localhost:${SERVER_PORT}/api/projects/${TEST_PROJECT_ALPHA}/agent/stop")
if ! echo "$response" | grep -q '"status":"stopped"'; then
    log_error "Failed to stop container: $response"
fi
log_success "Container stopped successfully"

# Verify container exists but is stopped
if ! docker ps -a --filter "name=autocoder-${TEST_PROJECT_ALPHA}" --format "{{.Status}}" | grep -q "Exited"; then
    log_error "Container should be in Exited state"
fi
log_success "Container persists in stopped state"

# Restart container
response=$(curl -s -X POST "http://localhost:${SERVER_PORT}/api/projects/${TEST_PROJECT_ALPHA}/agent/start" \
    -H "Content-Type: application/json" \
    -d '{"instruction": null}')
if ! echo "$response" | grep -q '"success":true'; then
    log_error "Failed to restart container: $response"
fi
sleep 2

if ! docker ps --filter "name=autocoder-${TEST_PROJECT_ALPHA}" --format "{{.Status}}" | grep -q "Up"; then
    log_error "Container failed to restart"
fi
log_success "Container restarted successfully"

# =============================================================================
# Test container removal
# =============================================================================
log_step "Testing container removal"

response=$(curl -s -X DELETE "http://localhost:${SERVER_PORT}/api/projects/${TEST_PROJECT_ALPHA}/agent/container")
if ! echo "$response" | grep -q '"status":"not_created"'; then
    log_error "Failed to remove container: $response"
fi

if docker ps -a --filter "name=autocoder-${TEST_PROJECT_ALPHA}" --format "{{.Names}}" | grep -q .; then
    log_error "Container still exists after removal"
fi
log_success "Container removed successfully"

# =============================================================================
# Test status endpoint
# =============================================================================
log_step "Testing status endpoint"

# Check running container status
status=$(curl -s "http://localhost:${SERVER_PORT}/api/projects/${TEST_PROJECT_BETA}/agent/status")
if ! echo "$status" | grep -q '"status":"running"'; then
    log_error "Status should be 'running': $status"
fi
if ! echo "$status" | grep -q '"idle_seconds"'; then
    log_error "Status should include idle_seconds"
fi
log_success "Status endpoint returns correct data"

# =============================================================================
# Delete test projects
# =============================================================================
log_step "Deleting test projects"

curl -s -X DELETE "http://localhost:${SERVER_PORT}/api/projects/${TEST_PROJECT_ALPHA}" > /dev/null
curl -s -X DELETE "http://localhost:${SERVER_PORT}/api/projects/${TEST_PROJECT_BETA}" > /dev/null
log_success "Projects deleted from registry"

# =============================================================================
# Summary
# =============================================================================
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}All tests passed!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Verified:"
echo "  - Docker image builds successfully"
echo "  - Multiple containers can run simultaneously"
echo "  - Each container has isolated project mount"
echo "  - Claude Code and beads CLI are installed"
echo "  - Containers can be stopped and restarted"
echo "  - Containers can be removed via API"
echo "  - Status endpoint tracks container state"
echo ""
