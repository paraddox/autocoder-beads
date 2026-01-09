"""
Progress Tracking Utilities
===========================

Functions for tracking and displaying progress of the autonomous coding agent.
Uses beads for git-backed issue tracking.
"""

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

from api.beads_client import BeadsClient

WEBHOOK_URL = os.environ.get("PROGRESS_N8N_WEBHOOK_URL")
PROGRESS_CACHE_FILE = ".progress_cache"


def has_features(project_dir: Path) -> bool:
    """
    Check if the project has features in beads.

    This is used to determine if the initializer agent needs to run.

    Returns True if .beads/ exists with issues.
    Returns False if no features exist (initializer needs to run).
    """
    # Direct JSONL check - most reliable, avoids bd CLI issues
    issues_file = project_dir / ".beads" / "issues.jsonl"
    if issues_file.exists():
        try:
            with open(issues_file, 'r') as f:
                for line in f:
                    if line.strip():
                        return True  # At least one issue exists
        except (PermissionError, OSError):
            pass

    # Fallback to client
    client = BeadsClient(project_dir)
    return client.has_features()


def count_passing_tests(project_dir: Path) -> tuple[int, int, int]:
    """
    Count passing, in_progress, and total tests.

    Args:
        project_dir: Directory containing the project

    Returns:
        (passing_count, in_progress_count, total_count)
    """
    client = BeadsClient(project_dir)
    if not client.is_initialized():
        return 0, 0, 0

    stats = client.get_stats()
    return (
        stats.get("passing", 0),
        stats.get("in_progress", 0),
        stats.get("total", 0),
    )


def get_all_passing_features(project_dir: Path) -> list[dict]:
    """
    Get all passing features for webhook notifications.

    Args:
        project_dir: Directory containing the project

    Returns:
        List of dicts with id, category, name for each passing feature
    """
    client = BeadsClient(project_dir)
    if not client.is_initialized():
        return []

    return client.get_all_passing()


def send_progress_webhook(passing: int, total: int, project_dir: Path) -> None:
    """Send webhook notification when progress increases."""
    if not WEBHOOK_URL:
        return  # Webhook not configured

    cache_file = project_dir / PROGRESS_CACHE_FILE
    previous = 0
    previous_passing_ids = set()

    # Read previous progress and passing feature IDs
    if cache_file.exists():
        try:
            cache_data = json.loads(cache_file.read_text())
            previous = cache_data.get("count", 0)
            previous_passing_ids = set(str(x) for x in cache_data.get("passing_ids", []))
        except Exception:
            previous = 0

    # Only notify if progress increased
    if passing > previous:
        # Find which features are now passing
        completed_tests = []
        current_passing_ids = []

        # Get all passing features
        all_passing = get_all_passing_features(project_dir)
        for feature in all_passing:
            feature_id = str(feature.get("id"))
            current_passing_ids.append(feature_id)
            if feature_id not in previous_passing_ids:
                # This feature is newly passing
                name = feature.get("name", f"Feature #{feature_id}")
                category = feature.get("category", "")
                if category:
                    completed_tests.append(f"{category} {name}")
                else:
                    completed_tests.append(name)

        payload = {
            "event": "test_progress",
            "passing": passing,
            "total": total,
            "percentage": round((passing / total) * 100, 1) if total > 0 else 0,
            "previous_passing": previous,
            "tests_completed_this_session": passing - previous,
            "completed_tests": completed_tests,
            "project": project_dir.name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        try:
            req = urllib.request.Request(
                WEBHOOK_URL,
                data=json.dumps([payload]).encode("utf-8"),  # n8n expects array
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"[Webhook notification failed: {e}]")

        # Update cache with count and passing IDs
        cache_file.write_text(
            json.dumps({"count": passing, "passing_ids": current_passing_ids})
        )
    else:
        # Update cache even if no change (for initial state)
        if not cache_file.exists():
            all_passing = get_all_passing_features(project_dir)
            current_passing_ids = [str(f.get("id")) for f in all_passing]
            cache_file.write_text(
                json.dumps({"count": passing, "passing_ids": current_passing_ids})
            )


def print_session_header(session_num: int, is_initializer: bool) -> None:
    """Print a formatted header for the session."""
    session_type = "INITIALIZER" if is_initializer else "CODING AGENT"

    print("\n" + "=" * 70)
    print(f"  SESSION {session_num}: {session_type}")
    print("=" * 70)
    print()


def print_progress_summary(project_dir: Path) -> None:
    """Print a summary of current progress."""
    passing, in_progress, total = count_passing_tests(project_dir)

    if total > 0:
        percentage = (passing / total) * 100
        status_parts = [f"{passing}/{total} tests passing ({percentage:.1f}%)"]
        if in_progress > 0:
            status_parts.append(f"{in_progress} in progress")
        print(f"\nProgress: {', '.join(status_parts)}")
        send_progress_webhook(passing, total, project_dir)
    else:
        print("\nProgress: No features yet")
