"""
Agent Router
============

API endpoints for agent/container control (start/stop/send instruction).
Uses ContainerManager for per-project Docker containers.
"""

import re
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..schemas import AgentActionResponse, AgentStartRequest, AgentStatus
from ..services.container_manager import (
    get_container_manager,
    check_docker_available,
    check_image_exists,
)

# Add root to path for imports
_root = Path(__file__).parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from registry import get_project_path
from progress import has_features
from prompts import get_initializer_prompt, get_coding_prompt, get_coding_prompt_yolo


def _get_project_path(project_name: str) -> Path:
    """Get project path from registry."""
    return get_project_path(project_name)


router = APIRouter(prefix="/api/projects/{project_name}/agent", tags=["agent"])


def validate_project_name(name: str) -> str:
    """Validate and sanitize project name to prevent path traversal."""
    if not re.match(r'^[a-zA-Z0-9_-]{1,50}$', name):
        raise HTTPException(
            status_code=400,
            detail="Invalid project name"
        )
    return name


def get_project_container(project_name: str):
    """Get the container manager for a project."""
    project_name = validate_project_name(project_name)
    project_dir = _get_project_path(project_name)

    if not project_dir:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{project_name}' not found in registry"
        )

    if not project_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Project directory not found: {project_dir}"
        )

    return get_container_manager(project_name, project_dir)


@router.get("/status", response_model=AgentStatus)
async def get_agent_status(project_name: str):
    """Get the current status of the container for a project."""
    manager = get_project_container(project_name)
    status_dict = manager.get_status_dict()

    return AgentStatus(
        status=status_dict["status"],
        container_name=status_dict["container_name"],
        started_at=manager.started_at,
        idle_seconds=status_dict["idle_seconds"],
        agent_running=status_dict.get("agent_running", False),
    )


def _get_agent_prompt(project_dir: Path, project_name: str, yolo_mode: bool = False) -> str:
    """
    Determine the appropriate prompt based on project state.

    - If no features exist: use initializer prompt
    - If features exist: use coding prompt (or yolo variant)
    """
    if has_features(project_dir, project_name):
        # Features exist, continue coding
        if yolo_mode:
            return get_coding_prompt_yolo(project_dir)
        return get_coding_prompt(project_dir)
    else:
        # No features, initialize from spec
        return get_initializer_prompt(project_dir)


@router.post("/start", response_model=AgentActionResponse)
async def start_agent(
    project_name: str,
    request: AgentStartRequest = AgentStartRequest(),
):
    """
    Start the container for a project and send the appropriate instruction.

    - Creates container if not exists
    - Starts container if stopped
    - Automatically determines if this is initialization or continuation
    - Sends the appropriate prompt (initializer or coding)
    """
    # Check Docker availability
    if not check_docker_available():
        raise HTTPException(
            status_code=503,
            detail="Docker is not available. Please ensure Docker is installed and running."
        )

    if not check_image_exists():
        raise HTTPException(
            status_code=503,
            detail="Container image 'autocoder-project' not found. Run: docker build -f Dockerfile.project -t autocoder-project ."
        )

    manager = get_project_container(project_name)
    project_dir = _get_project_path(project_name)

    # Determine the instruction to send
    instruction = request.instruction
    if not instruction:
        # Auto-determine based on project state
        try:
            instruction = _get_agent_prompt(project_dir, project_name, request.yolo_mode)
            is_init = not has_features(project_dir, project_name)
            print(f"[Agent] Auto-selected {'initializer' if is_init else 'coding'} prompt for {project_name}")
        except FileNotFoundError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not load prompt: {e}"
            )

    success, message = await manager.start(instruction=instruction)

    return AgentActionResponse(
        success=success,
        status=manager.status,
        message=message,
    )


@router.post("/stop", response_model=AgentActionResponse)
async def stop_agent(project_name: str):
    """Stop the container for a project (does not remove it)."""
    manager = get_project_container(project_name)
    success, message = await manager.stop()

    return AgentActionResponse(
        success=success,
        status=manager.status,
        message=message,
    )


@router.post("/instruction", response_model=AgentActionResponse)
async def send_instruction(project_name: str, request: AgentStartRequest):
    """
    Send an instruction to the running container.

    Container must already be running.
    """
    if not request.instruction:
        raise HTTPException(
            status_code=400,
            detail="instruction is required"
        )

    manager = get_project_container(project_name)

    if manager.status != "running":
        raise HTTPException(
            status_code=400,
            detail=f"Container is not running (status: {manager.status})"
        )

    success, message = await manager.send_instruction(request.instruction)

    return AgentActionResponse(
        success=success,
        status=manager.status,
        message=message,
    )


@router.delete("/container", response_model=AgentActionResponse)
async def remove_container(project_name: str):
    """Remove the container completely (for cleanup)."""
    manager = get_project_container(project_name)
    success, message = await manager.remove()

    return AgentActionResponse(
        success=success,
        status=manager.status,
        message=message,
    )


@router.post("/container/start", response_model=AgentActionResponse)
async def start_container_only(project_name: str):
    """
    Start the container without starting the agent.

    This is useful for editing tasks when you don't want to start
    the agent consuming API credits. The container will stay running
    until idle timeout (60 min).
    """
    # Check Docker availability
    if not check_docker_available():
        raise HTTPException(
            status_code=503,
            detail="Docker is not available. Please ensure Docker is installed and running."
        )

    if not check_image_exists():
        raise HTTPException(
            status_code=503,
            detail="Container image 'autocoder-project' not found. Run: docker build -f Dockerfile.project -t autocoder-project ."
        )

    manager = get_project_container(project_name)
    success, message = await manager.start_container_only()

    return AgentActionResponse(
        success=success,
        status=manager.status,
        message=message,
    )


# Legacy endpoints for backwards compatibility
@router.post("/pause", response_model=AgentActionResponse)
async def pause_agent(project_name: str):
    """
    Pause endpoint (deprecated).

    Containers don't support pause - use stop instead.
    """
    raise HTTPException(
        status_code=400,
        detail="Pause is not supported for containers. Use stop instead."
    )


@router.post("/resume", response_model=AgentActionResponse)
async def resume_agent(project_name: str):
    """
    Resume endpoint (deprecated).

    Use start to restart a stopped container.
    """
    raise HTTPException(
        status_code=400,
        detail="Resume is not supported for containers. Use start instead."
    )
