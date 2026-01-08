#!/usr/bin/env python3
"""
MCP Server for Feature Management
==================================

Provides tools to manage features in the autonomous coding system,
using beads for git-backed issue tracking.

Tools:
- feature_get_stats: Get progress statistics
- feature_get_next: Get next feature to implement
- feature_get_for_regression: Get random passing features for testing
- feature_mark_passing: Mark a feature as passing
- feature_skip: Skip a feature (move to end of queue)
- feature_mark_in_progress: Mark a feature as in-progress
- feature_clear_in_progress: Clear in-progress status
- feature_create_bulk: Create multiple features at once
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# Add parent directory to path so we can import from api module
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.beads_client import BeadsClient

# Configuration from environment
PROJECT_DIR = Path(os.environ.get("PROJECT_DIR", ".")).resolve()


# Pydantic models for input validation
class MarkPassingInput(BaseModel):
    """Input for marking a feature as passing."""
    feature_id: str = Field(..., description="The ID of the feature to mark as passing")


class SkipFeatureInput(BaseModel):
    """Input for skipping a feature."""
    feature_id: str = Field(..., description="The ID of the feature to skip")


class MarkInProgressInput(BaseModel):
    """Input for marking a feature as in-progress."""
    feature_id: str = Field(..., description="The ID of the feature to mark as in-progress")


class ClearInProgressInput(BaseModel):
    """Input for clearing in-progress status."""
    feature_id: str = Field(..., description="The ID of the feature to clear in-progress status")


class RegressionInput(BaseModel):
    """Input for getting regression features."""
    limit: int = Field(default=3, ge=1, le=10, description="Maximum number of passing features to return")


class FeatureCreateItem(BaseModel):
    """Schema for creating a single feature."""
    category: str = Field(..., min_length=1, max_length=100, description="Feature category")
    name: str = Field(..., min_length=1, max_length=255, description="Feature name")
    description: str = Field(..., min_length=1, description="Detailed description")
    steps: list[str] = Field(..., min_length=1, description="Implementation/test steps")


class BulkCreateInput(BaseModel):
    """Input for bulk creating features."""
    features: list[FeatureCreateItem] = Field(..., min_length=1, description="List of features to create")


# Global beads client (initialized on startup)
_beads_client: BeadsClient | None = None


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    """Initialize beads client on startup."""
    global _beads_client

    # Create project directory if it doesn't exist
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize beads client
    _beads_client = BeadsClient(PROJECT_DIR)

    # Initialize beads if not already done
    _beads_client.init()

    yield

    # Cleanup (nothing to dispose for beads)
    _beads_client = None


# Initialize the MCP server
mcp = FastMCP("features", lifespan=server_lifespan)


def get_client() -> BeadsClient:
    """Get the beads client."""
    if _beads_client is None:
        raise RuntimeError("Beads client not initialized")
    return _beads_client


@mcp.tool()
def feature_get_stats() -> str:
    """Get statistics about feature completion progress.

    Returns the number of passing features, in-progress features, total features,
    and completion percentage. Use this to track overall progress of the implementation.

    Returns:
        JSON with: passing (int), in_progress (int), total (int), percentage (float)
    """
    client = get_client()
    stats = client.get_stats()
    return json.dumps(stats, indent=2)


@mcp.tool()
def feature_get_next() -> str:
    """Get the highest-priority pending feature to work on.

    Returns the feature with the lowest priority number that has passes=false.
    Use this at the start of each coding session to determine what to implement next.

    Returns:
        JSON with feature details (id, priority, category, name, description, steps, passes, in_progress)
        or error message if all features are passing.
    """
    client = get_client()
    feature = client.get_next()

    if feature is None:
        return json.dumps({"error": "All features are passing! No more work to do."})

    return json.dumps(feature, indent=2)


@mcp.tool()
def feature_get_for_regression(
    limit: Annotated[int, Field(default=3, ge=1, le=10, description="Maximum number of passing features to return")] = 3
) -> str:
    """Get random passing features for regression testing.

    Returns a random selection of features that are currently passing.
    Use this to verify that previously implemented features still work
    after making changes.

    Args:
        limit: Maximum number of features to return (1-10, default 3)

    Returns:
        JSON with: features (list of feature objects), count (int)
    """
    client = get_client()
    features = client.get_for_regression(limit)

    return json.dumps({
        "features": features,
        "count": len(features)
    }, indent=2)


@mcp.tool()
def feature_mark_passing(
    feature_id: Annotated[str, Field(description="The ID of the feature to mark as passing")]
) -> str:
    """Mark a feature as passing after successful implementation.

    Updates the feature's passes field to true and clears the in_progress flag.
    Use this after you have implemented the feature and verified it works correctly.

    Args:
        feature_id: The ID of the feature to mark as passing

    Returns:
        JSON with the updated feature details, or error if not found.
    """
    client = get_client()
    feature = client.mark_passing(feature_id)

    if feature is None:
        return json.dumps({"error": f"Feature with ID {feature_id} not found"})

    return json.dumps(feature, indent=2)


@mcp.tool()
def feature_skip(
    feature_id: Annotated[str, Field(description="The ID of the feature to skip")]
) -> str:
    """Skip a feature by moving it to the end of the priority queue.

    Use this when a feature cannot be implemented yet due to:
    - Dependencies on other features that aren't implemented yet
    - External blockers (missing assets, unclear requirements)
    - Technical prerequisites that need to be addressed first

    The feature's priority is set to P4, so it will be
    worked on after all other pending features. Also clears the in_progress
    flag so the feature returns to "pending" status.

    Args:
        feature_id: The ID of the feature to skip

    Returns:
        JSON with skip details: id, name, old_priority, new_priority, message
    """
    client = get_client()
    result = client.skip(feature_id)

    if result is None:
        return json.dumps({"error": f"Feature with ID {feature_id} not found"})

    if "error" in result:
        return json.dumps(result)

    return json.dumps(result, indent=2)


@mcp.tool()
def feature_mark_in_progress(
    feature_id: Annotated[str, Field(description="The ID of the feature to mark as in-progress")]
) -> str:
    """Mark a feature as in-progress. Call immediately after feature_get_next().

    This prevents other agent sessions from working on the same feature.
    Use this as soon as you retrieve a feature to work on.

    Args:
        feature_id: The ID of the feature to mark as in-progress

    Returns:
        JSON with the updated feature details, or error if not found or already in-progress.
    """
    client = get_client()

    # Check current state
    current = client.get_feature(feature_id)
    if current is None:
        return json.dumps({"error": f"Feature with ID {feature_id} not found"})

    if current.get("passes"):
        return json.dumps({"error": f"Feature with ID {feature_id} is already passing"})

    if current.get("in_progress"):
        return json.dumps({"error": f"Feature with ID {feature_id} is already in-progress"})

    feature = client.mark_in_progress(feature_id)

    if feature is None:
        return json.dumps({"error": f"Failed to mark feature {feature_id} as in-progress"})

    return json.dumps(feature, indent=2)


@mcp.tool()
def feature_clear_in_progress(
    feature_id: Annotated[str, Field(description="The ID of the feature to clear in-progress status")]
) -> str:
    """Clear in-progress status from a feature.

    Use this when abandoning a feature or manually unsticking a stuck feature.
    The feature will return to the pending queue.

    Args:
        feature_id: The ID of the feature to clear in-progress status

    Returns:
        JSON with the updated feature details, or error if not found.
    """
    client = get_client()
    feature = client.clear_in_progress(feature_id)

    if feature is None:
        return json.dumps({"error": f"Feature with ID {feature_id} not found"})

    return json.dumps(feature, indent=2)


@mcp.tool()
def feature_create_bulk(
    features: Annotated[list[dict], Field(description="List of features to create, each with category, name, description, and steps")]
) -> str:
    """Create multiple features in a single operation.

    Features are assigned sequential priorities based on their order.
    All features start with passes=false.

    This is typically used by the initializer agent to set up the initial
    feature list from the app specification.

    Args:
        features: List of features to create, each with:
            - category (str): Feature category
            - name (str): Feature name
            - description (str): Detailed description
            - steps (list[str]): Implementation/test steps

    Returns:
        JSON with: created (int) - number of features created
    """
    client = get_client()

    # Validate required fields
    for i, feature_data in enumerate(features):
        if not all(key in feature_data for key in ["category", "name", "description", "steps"]):
            return json.dumps({
                "error": f"Feature at index {i} missing required fields (category, name, description, steps)"
            })

    created = client.bulk_create(features)
    return json.dumps({"created": created}, indent=2)


if __name__ == "__main__":
    mcp.run()
