"""
Features Router
===============

API endpoints for feature/test case management using beads.
Routes through container when running, falls back to direct BeadsClient when stopped.
"""

import logging
import re
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..schemas import (
    FeatureCreate,
    FeatureListResponse,
    FeatureResponse,
    FeatureUpdate,
)
from ..services.container_beads import ContainerBeadsClient

# Add parent to path for imports
_root = Path(__file__).parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from api.beads_client import BeadsClient

logger = logging.getLogger(__name__)


def _get_project_path(project_name: str) -> Path:
    """Get project path from registry."""
    from registry import get_project_path
    return get_project_path(project_name)


router = APIRouter(prefix="/api/projects/{project_name}/features", tags=["features"])


def validate_project_name(name: str) -> str:
    """Validate and sanitize project name to prevent path traversal."""
    if not re.match(r'^[a-zA-Z0-9_-]{1,50}$', name):
        raise HTTPException(
            status_code=400,
            detail="Invalid project name"
        )
    return name


def _is_container_running(project_name: str) -> bool:
    """Check if the container is running for this project."""
    from ..services.container_manager import _managers, _managers_lock

    with _managers_lock:
        manager = _managers.get(project_name)
        return manager is not None and manager.status == "running"


def _get_beads_client(project_dir: Path) -> BeadsClient:
    """Get a BeadsClient for the project (fallback when container not running)."""
    return BeadsClient(project_dir)


def feature_to_response(feature: dict) -> FeatureResponse:
    """Convert a feature dict to a FeatureResponse."""
    return FeatureResponse(
        id=str(feature.get("id", "")),
        priority=feature.get("priority", 999),
        category=feature.get("category", ""),
        name=feature.get("name", ""),
        description=feature.get("description", ""),
        steps=feature.get("steps", []),
        passes=feature.get("passes", False),
        in_progress=feature.get("in_progress", False),
    )


@router.get("", response_model=FeatureListResponse)
async def list_features(project_name: str):
    """
    List all features for a project organized by status.

    Returns features in three lists:
    - pending: passes=False, not currently being worked on
    - in_progress: features currently being worked on
    - done: passes=True

    Uses cached data when container is running to avoid permission issues.
    Falls back to direct BeadsClient when container is stopped.
    """
    project_name = validate_project_name(project_name)
    project_dir = _get_project_path(project_name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found in registry")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    # Check if container is running - use cache to avoid permission issues
    from ..services.feature_poller import get_cached_features

    if _is_container_running(project_name):
        # Read from cache
        cached_features = get_cached_features(project_name)
        if cached_features:  # Cache has data
            pending = []
            in_progress = []
            done = []

            for f in cached_features:
                feature_response = feature_to_response(f)
                if f.get("passes"):
                    done.append(feature_response)
                elif f.get("in_progress"):
                    in_progress.append(feature_response)
                else:
                    pending.append(feature_response)

            return FeatureListResponse(
                pending=pending,
                in_progress=in_progress,
                done=done,
            )

    # Fallback: read directly from BeadsClient
    client = _get_beads_client(project_dir)

    # If beads is not initialized, return empty lists
    if not client.is_initialized():
        return FeatureListResponse(pending=[], in_progress=[], done=[])

    try:
        all_features = client.list_all()

        pending = []
        in_progress = []
        done = []

        for f in all_features:
            feature_response = feature_to_response(f)
            if f.get("passes"):
                done.append(feature_response)
            elif f.get("in_progress"):
                in_progress.append(feature_response)
            else:
                pending.append(feature_response)

        return FeatureListResponse(
            pending=pending,
            in_progress=in_progress,
            done=done,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in list_features")
        raise HTTPException(status_code=500, detail="Error occurred while listing features")


@router.post("", response_model=FeatureResponse)
async def create_feature(project_name: str, feature: FeatureCreate):
    """Create a new feature/test case manually."""
    project_name = validate_project_name(project_name)
    project_dir = _get_project_path(project_name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found in registry")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    # Determine priority
    priority = feature.priority if feature.priority is not None else 999

    # Use container client if running
    if _is_container_running(project_name):
        try:
            container_client = ContainerBeadsClient(project_name)
            feature_id = await container_client.create(
                name=feature.name,
                category=feature.category,
                description=feature.description,
                steps=feature.steps,
                priority=priority,
            )

            if not feature_id:
                raise HTTPException(status_code=500, detail="Failed to create feature")

            # Get the created feature
            created = await container_client.get_feature(feature_id)
            if not created:
                raise HTTPException(status_code=500, detail="Feature created but could not be retrieved")

            return feature_to_response(created)
        except RuntimeError as e:
            logger.error(f"Container command failed: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create feature: {e}")

    # Fallback to direct BeadsClient
    client = _get_beads_client(project_dir)

    try:
        # Initialize beads if needed
        if not client.is_initialized():
            client.init()

        # Create the feature
        feature_id = client.create(
            category=feature.category,
            name=feature.name,
            description=feature.description,
            steps=feature.steps,
            priority=priority,
        )

        if not feature_id:
            raise HTTPException(status_code=500, detail="Failed to create feature")

        # Get the created feature
        created = client.get_feature(feature_id)
        if not created:
            raise HTTPException(status_code=500, detail="Feature created but could not be retrieved")

        return feature_to_response(created)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create feature")
        raise HTTPException(status_code=500, detail="Failed to create feature")


@router.get("/{feature_id}", response_model=FeatureResponse)
async def get_feature(project_name: str, feature_id: str):
    """Get details of a specific feature."""
    project_name = validate_project_name(project_name)
    project_dir = _get_project_path(project_name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found in registry")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    # Use container client if running
    if _is_container_running(project_name):
        try:
            container_client = ContainerBeadsClient(project_name)
            feature = await container_client.get_feature(feature_id)

            if not feature:
                raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

            return feature_to_response(feature)
        except RuntimeError as e:
            logger.error(f"Container command failed: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get feature: {e}")

    # Fallback to direct BeadsClient
    client = _get_beads_client(project_dir)

    if not client.is_initialized():
        raise HTTPException(status_code=404, detail="No features found")

    try:
        feature = client.get_feature(feature_id)

        if not feature:
            raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

        return feature_to_response(feature)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in get_feature")
        raise HTTPException(status_code=500, detail="Error occurred")


@router.delete("/{feature_id}")
async def delete_feature(project_name: str, feature_id: str):
    """Delete a feature."""
    project_name = validate_project_name(project_name)
    project_dir = _get_project_path(project_name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found in registry")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    # Use container client if running
    if _is_container_running(project_name):
        try:
            container_client = ContainerBeadsClient(project_name)

            # Check if feature exists first
            feature = await container_client.get_feature(feature_id)
            if not feature:
                raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

            success = await container_client.delete(feature_id)

            if not success:
                raise HTTPException(status_code=500, detail="Failed to delete feature")

            return {"success": True, "message": f"Feature {feature_id} deleted"}
        except RuntimeError as e:
            logger.error(f"Container command failed: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete feature: {e}")
        except HTTPException:
            raise

    # Fallback to direct BeadsClient
    client = _get_beads_client(project_dir)

    if not client.is_initialized():
        raise HTTPException(status_code=404, detail="No features found")

    try:
        # Check if feature exists first
        feature = client.get_feature(feature_id)
        if not feature:
            raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

        success = client.delete(feature_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete feature")

        return {"success": True, "message": f"Feature {feature_id} deleted"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete feature")
        raise HTTPException(status_code=500, detail="Failed to delete feature")


@router.patch("/{feature_id}/skip")
async def skip_feature(project_name: str, feature_id: str):
    """
    Mark a feature as skipped by moving it to the end of the priority queue.

    This doesn't delete the feature but gives it a very low priority
    so it will be processed last.
    """
    project_name = validate_project_name(project_name)
    project_dir = _get_project_path(project_name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found in registry")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    # Use container client if running
    if _is_container_running(project_name):
        try:
            container_client = ContainerBeadsClient(project_name)
            result = await container_client.skip(feature_id)

            if result is None:
                raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

            if "error" in result:
                raise HTTPException(status_code=400, detail=result["error"])

            return {"success": True, "message": f"Feature {feature_id} moved to end of queue"}
        except RuntimeError as e:
            logger.error(f"Container command failed: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to skip feature: {e}")
        except HTTPException:
            raise

    # Fallback to direct BeadsClient
    client = _get_beads_client(project_dir)

    if not client.is_initialized():
        raise HTTPException(status_code=404, detail="No features found")

    try:
        result = client.skip(feature_id)

        if result is None:
            raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return {"success": True, "message": f"Feature {feature_id} moved to end of queue"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to skip feature")
        raise HTTPException(status_code=500, detail="Failed to skip feature")


@router.patch("/{feature_id}", response_model=FeatureResponse)
async def update_feature(project_name: str, feature_id: str, update: FeatureUpdate):
    """
    Update a feature's fields.

    Only the provided fields will be updated; others remain unchanged.
    """
    project_name = validate_project_name(project_name)
    project_dir = _get_project_path(project_name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found in registry")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    # Use container client if running
    if _is_container_running(project_name):
        try:
            container_client = ContainerBeadsClient(project_name)

            # Check if feature exists
            feature = await container_client.get_feature(feature_id)
            if not feature:
                raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

            # Update the feature
            updated = await container_client.update(
                feature_id,
                name=update.name,
                description=update.description,
                priority=update.priority,
                category=update.category,
                steps=update.steps,
            )

            if not updated:
                raise HTTPException(status_code=500, detail="Failed to update feature")

            return feature_to_response(updated)
        except RuntimeError as e:
            logger.error(f"Container command failed: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update feature: {e}")
        except HTTPException:
            raise

    # Fallback to direct BeadsClient
    client = _get_beads_client(project_dir)

    if not client.is_initialized():
        raise HTTPException(status_code=404, detail="No features found")

    try:
        # Check if feature exists
        feature = client.get_feature(feature_id)
        if not feature:
            raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

        # Update the feature
        updated = client.update(
            feature_id,
            name=update.name,
            description=update.description,
            priority=update.priority,
            category=update.category,
            steps=update.steps,
        )

        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update feature")

        return feature_to_response(updated)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to update feature")
        raise HTTPException(status_code=500, detail="Failed to update feature")


@router.patch("/{feature_id}/reopen")
async def reopen_feature(project_name: str, feature_id: str):
    """
    Reopen a completed feature (move it back to pending).
    """
    project_name = validate_project_name(project_name)
    project_dir = _get_project_path(project_name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found in registry")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    # Use container client if running
    if _is_container_running(project_name):
        try:
            container_client = ContainerBeadsClient(project_name)

            # Check if feature exists and is closed
            feature = await container_client.get_feature(feature_id)
            if not feature:
                raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

            if not feature.get("passes"):
                raise HTTPException(status_code=400, detail="Feature is not completed, cannot reopen")

            # Reopen the feature
            reopened = await container_client.reopen(feature_id)

            if not reopened:
                raise HTTPException(status_code=500, detail="Failed to reopen feature")

            return {"success": True, "message": f"Feature {feature_id} reopened"}
        except RuntimeError as e:
            logger.error(f"Container command failed: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to reopen feature: {e}")
        except HTTPException:
            raise

    # Fallback to direct BeadsClient
    client = _get_beads_client(project_dir)

    if not client.is_initialized():
        raise HTTPException(status_code=404, detail="No features found")

    try:
        # Check if feature exists and is closed
        feature = client.get_feature(feature_id)
        if not feature:
            raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")

        if not feature.get("passes"):
            raise HTTPException(status_code=400, detail="Feature is not completed, cannot reopen")

        # Reopen the feature
        reopened = client.reopen(feature_id)

        if not reopened:
            raise HTTPException(status_code=500, detail="Failed to reopen feature")

        return {"success": True, "message": f"Feature {feature_id} reopened"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to reopen feature")
        raise HTTPException(status_code=500, detail="Failed to reopen feature")
