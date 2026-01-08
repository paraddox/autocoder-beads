"""
Beads Client
============

Python wrapper for the beads CLI, providing feature management using
git-backed issue tracking instead of SQLite.
"""

import json
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict


class FeatureDict(TypedDict, total=False):
    """Feature dictionary matching the previous SQLite model format."""
    id: str
    priority: int
    category: str
    name: str
    description: str
    steps: list[str]
    passes: bool
    in_progress: bool


@dataclass
class BeadsClient:
    """
    Client for managing features using the beads issue tracker.

    Wraps the `bd` CLI to provide feature management operations,
    replacing the previous SQLite-based storage.
    """

    project_dir: Path
    prefix: str = "feat"

    def __post_init__(self):
        self.project_dir = Path(self.project_dir).resolve()
        self.beads_dir = self.project_dir / ".beads"

    def _run_bd(
        self,
        args: list[str],
        check: bool = True,
        capture_output: bool = True
    ) -> subprocess.CompletedProcess:
        """
        Execute a bd command in the project directory.

        Args:
            args: Command arguments (without 'bd' prefix)
            check: Raise on non-zero exit code
            capture_output: Capture stdout/stderr

        Returns:
            CompletedProcess with command results
        """
        cmd = ["bd", "--db", str(self.beads_dir)] + args
        return subprocess.run(
            cmd,
            cwd=self.project_dir,
            check=check,
            capture_output=capture_output,
            text=True,
        )

    def _parse_json_output(self, result: subprocess.CompletedProcess) -> list | dict:
        """Parse JSON output from bd command."""
        if not result.stdout.strip():
            return []
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

    def _priority_to_beads(self, priority: int) -> str:
        """Convert numeric priority to beads P0-P4 format."""
        if priority <= 0:
            return "P0"
        elif priority == 1:
            return "P1"
        elif priority == 2:
            return "P2"
        elif priority == 3:
            return "P3"
        else:
            return "P4"

    def _beads_to_priority(self, beads_priority: str) -> int:
        """Convert beads P0-P4 format to numeric priority."""
        mapping = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
        return mapping.get(beads_priority.upper(), 4)

    def _steps_to_description(self, description: str, steps: list[str]) -> str:
        """Append steps as markdown checklist to description."""
        if not steps:
            return description

        steps_md = "\n\n## Steps\n" + "\n".join(f"- [ ] {step}" for step in steps)
        return description + steps_md

    def _parse_steps_from_description(self, description: str) -> tuple[str, list[str]]:
        """Extract steps checklist from description."""
        if "## Steps" not in description:
            return description, []

        parts = description.split("## Steps", 1)
        base_description = parts[0].rstrip()
        steps_section = parts[1] if len(parts) > 1 else ""

        steps = []
        for line in steps_section.strip().split("\n"):
            line = line.strip()
            if line.startswith("- [ ]"):
                steps.append(line[5:].strip())
            elif line.startswith("- [x]"):
                steps.append(line[5:].strip())

        return base_description, steps

    def _extract_label_value(self, labels: list[str], prefix: str) -> str | None:
        """Extract value from a label like 'category:value'."""
        for label in labels:
            if label.startswith(f"{prefix}:"):
                return label[len(prefix) + 1:]
        return None

    def _issue_to_feature(self, issue: dict) -> FeatureDict:
        """Convert a beads issue to feature dictionary format."""
        labels = issue.get("labels", [])

        # Extract category from labels or title
        category = self._extract_label_value(labels, "category") or ""

        # Parse original priority from label
        priority_label = self._extract_label_value(labels, "priority")
        if priority_label and priority_label.isdigit():
            priority = int(priority_label)
        else:
            priority = self._beads_to_priority(issue.get("priority", "P4"))

        # Parse steps from description
        full_description = issue.get("description", "")
        description, steps = self._parse_steps_from_description(full_description)

        # Map status to passes/in_progress
        status = issue.get("status", "open")
        passes = status == "closed"
        in_progress = status == "in_progress"

        return FeatureDict(
            id=issue.get("id", ""),
            priority=priority,
            category=category,
            name=issue.get("title", ""),
            description=description,
            steps=steps,
            passes=passes,
            in_progress=in_progress,
        )

    def is_initialized(self) -> bool:
        """Check if beads is initialized in the project directory."""
        return self.beads_dir.exists() and (self.beads_dir / "config.yaml").exists()

    def init(self) -> bool:
        """
        Initialize beads in the project directory.

        Returns:
            True if initialized successfully or already initialized
        """
        if self.is_initialized():
            return True

        try:
            self._run_bd([
                "init",
                "--prefix", self.prefix,
                "--quiet",
                "--skip-hooks",
            ], check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def get_stats(self) -> dict:
        """
        Get statistics about feature completion.

        Returns:
            Dict with: passing, in_progress, total, percentage
        """
        if not self.is_initialized():
            return {"passing": 0, "in_progress": 0, "total": 0, "percentage": 0.0}

        try:
            result = self._run_bd(["stats", "--json"], check=False)
            if result.returncode != 0:
                return {"passing": 0, "in_progress": 0, "total": 0, "percentage": 0.0}

            stats = self._parse_json_output(result)
            if isinstance(stats, dict):
                closed = stats.get("closed", 0)
                in_progress = stats.get("in_progress", 0)
                open_count = stats.get("open", 0)
                total = closed + in_progress + open_count
                percentage = round((closed / total) * 100, 1) if total > 0 else 0.0

                return {
                    "passing": closed,
                    "in_progress": in_progress,
                    "total": total,
                    "percentage": percentage,
                }
        except Exception:
            pass

        return {"passing": 0, "in_progress": 0, "total": 0, "percentage": 0.0}

    def has_features(self) -> bool:
        """Check if any features exist."""
        if not self.is_initialized():
            return False

        stats = self.get_stats()
        return stats.get("total", 0) > 0

    def get_next(self) -> FeatureDict | None:
        """
        Get the highest-priority pending feature.

        Returns:
            Feature dict or None if all features are done
        """
        if not self.is_initialized():
            return None

        try:
            # Get open issues sorted by priority
            result = self._run_bd([
                "list",
                "--status=open",
                "--json",
            ], check=False)

            if result.returncode != 0:
                return None

            issues = self._parse_json_output(result)
            if not issues:
                return None

            # Sort by priority label (numeric) then by id
            def sort_key(issue):
                labels = issue.get("labels", [])
                priority_label = self._extract_label_value(labels, "priority")
                if priority_label and priority_label.isdigit():
                    return (int(priority_label), issue.get("id", ""))
                return (999, issue.get("id", ""))

            issues.sort(key=sort_key)
            return self._issue_to_feature(issues[0])

        except Exception:
            return None

    def get_for_regression(self, limit: int = 3) -> list[FeatureDict]:
        """
        Get random passing features for regression testing.

        Args:
            limit: Maximum number of features to return (1-10)

        Returns:
            List of feature dicts
        """
        if not self.is_initialized():
            return []

        limit = max(1, min(10, limit))

        try:
            result = self._run_bd([
                "list",
                "--status=closed",
                "--json",
            ], check=False)

            if result.returncode != 0:
                return []

            issues = self._parse_json_output(result)
            if not issues:
                return []

            # Random sample
            if len(issues) <= limit:
                selected = issues
            else:
                selected = random.sample(issues, limit)

            return [self._issue_to_feature(issue) for issue in selected]

        except Exception:
            return []

    def create(
        self,
        category: str,
        name: str,
        description: str,
        steps: list[str],
        priority: int = 999,
    ) -> str | None:
        """
        Create a new feature issue.

        Args:
            category: Feature category
            name: Feature name (becomes title)
            description: Feature description
            steps: Implementation steps
            priority: Numeric priority (lower = higher priority)

        Returns:
            Issue ID if created, None on failure
        """
        if not self.is_initialized():
            if not self.init():
                return None

        beads_priority = self._priority_to_beads(priority)
        full_description = self._steps_to_description(description, steps)
        labels = [f"category:{category}", f"priority:{priority}"]

        try:
            result = self._run_bd([
                "create",
                "--title", name,
                "--description", full_description,
                "--priority", beads_priority,
                "--labels", ",".join(labels),
                "--type", "task",
                "--json",
            ], check=False)

            if result.returncode != 0:
                return None

            output = self._parse_json_output(result)
            if isinstance(output, dict):
                return output.get("id")

            return None

        except Exception:
            return None

    def bulk_create(self, features: list[dict]) -> int:
        """
        Create multiple features.

        Args:
            features: List of dicts with category, name, description, steps

        Returns:
            Number of features created
        """
        if not self.is_initialized():
            if not self.init():
                return 0

        created = 0
        for i, feature_data in enumerate(features):
            category = feature_data.get("category", "")
            name = feature_data.get("name", "")
            description = feature_data.get("description", "")
            steps = feature_data.get("steps", [])
            priority = i + 1  # Sequential priorities

            if self.create(category, name, description, steps, priority):
                created += 1

        return created

    def mark_passing(self, feature_id: str) -> FeatureDict | None:
        """
        Mark a feature as passing (close the issue).

        Args:
            feature_id: The feature/issue ID

        Returns:
            Updated feature dict or None on failure
        """
        try:
            result = self._run_bd([
                "close", feature_id,
            ], check=False)

            if result.returncode != 0:
                return None

            return self.get_feature(feature_id)

        except Exception:
            return None

    def mark_in_progress(self, feature_id: str) -> FeatureDict | None:
        """
        Mark a feature as in-progress.

        Args:
            feature_id: The feature/issue ID

        Returns:
            Updated feature dict or None on failure
        """
        try:
            result = self._run_bd([
                "update", feature_id,
                "--status=in_progress",
            ], check=False)

            if result.returncode != 0:
                return None

            return self.get_feature(feature_id)

        except Exception:
            return None

    def clear_in_progress(self, feature_id: str) -> FeatureDict | None:
        """
        Clear in-progress status (set back to open).

        Args:
            feature_id: The feature/issue ID

        Returns:
            Updated feature dict or None on failure
        """
        try:
            result = self._run_bd([
                "update", feature_id,
                "--status=open",
            ], check=False)

            if result.returncode != 0:
                return None

            return self.get_feature(feature_id)

        except Exception:
            return None

    def skip(self, feature_id: str) -> dict | None:
        """
        Skip a feature by setting priority to P4.

        Args:
            feature_id: The feature/issue ID

        Returns:
            Dict with skip details or None on failure
        """
        # Get current feature to get old priority
        feature = self.get_feature(feature_id)
        if not feature:
            return None

        if feature.get("passes"):
            return {"error": "Cannot skip a feature that is already passing"}

        old_priority = feature.get("priority", 0)

        try:
            # Update priority to P4 and clear in_progress
            result = self._run_bd([
                "update", feature_id,
                "--priority=P4",
                "--status=open",
            ], check=False)

            if result.returncode != 0:
                return None

            # Update the priority label to a high number
            new_priority = 9999
            self._run_bd([
                "label", feature_id,
                "--remove", f"priority:{old_priority}",
            ], check=False)
            self._run_bd([
                "label", feature_id,
                "--add", f"priority:{new_priority}",
            ], check=False)

            return {
                "id": feature_id,
                "name": feature.get("name", ""),
                "old_priority": old_priority,
                "new_priority": new_priority,
                "message": f"Feature '{feature.get('name', '')}' moved to end of queue",
            }

        except Exception:
            return None

    def get_feature(self, feature_id: str) -> FeatureDict | None:
        """
        Get a single feature by ID.

        Args:
            feature_id: The feature/issue ID

        Returns:
            Feature dict or None if not found
        """
        try:
            result = self._run_bd([
                "show", feature_id,
                "--json",
            ], check=False)

            if result.returncode != 0:
                return None

            issue = self._parse_json_output(result)
            if isinstance(issue, dict) and issue:
                return self._issue_to_feature(issue)

            return None

        except Exception:
            return None

    def list_all(self) -> list[FeatureDict]:
        """
        List all features (open, in_progress, closed).

        Returns:
            List of feature dicts
        """
        if not self.is_initialized():
            return []

        all_features = []

        for status in ["open", "in_progress", "closed"]:
            try:
                result = self._run_bd([
                    "list",
                    f"--status={status}",
                    "--json",
                ], check=False)

                if result.returncode == 0:
                    issues = self._parse_json_output(result)
                    for issue in issues:
                        all_features.append(self._issue_to_feature(issue))
            except Exception:
                continue

        # Sort by priority
        all_features.sort(key=lambda f: f.get("priority", 999))
        return all_features

    def delete(self, feature_id: str) -> bool:
        """
        Delete a feature.

        Args:
            feature_id: The feature/issue ID

        Returns:
            True if deleted, False otherwise
        """
        try:
            result = self._run_bd([
                "delete", feature_id,
                "--force",
            ], check=False)

            return result.returncode == 0

        except Exception:
            return False

    def get_all_passing(self) -> list[dict]:
        """
        Get all passing features for webhook notifications.

        Returns:
            List of dicts with id, category, name
        """
        if not self.is_initialized():
            return []

        try:
            result = self._run_bd([
                "list",
                "--status=closed",
                "--json",
            ], check=False)

            if result.returncode != 0:
                return []

            issues = self._parse_json_output(result)
            features = []

            for issue in issues:
                labels = issue.get("labels", [])
                category = self._extract_label_value(labels, "category") or ""
                features.append({
                    "id": issue.get("id", ""),
                    "category": category,
                    "name": issue.get("title", ""),
                })

            return features

        except Exception:
            return []
