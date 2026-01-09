"""
Container Manager
=================

Manages Docker containers for per-project Claude Code execution.
Each project gets its own sandboxed container.
"""

import asyncio
import logging
import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Literal, Set

logger = logging.getLogger(__name__)

# Container image name
CONTAINER_IMAGE = "autocoder-project"

# Idle timeout in minutes
IDLE_TIMEOUT_MINUTES = 60

# Patterns for sensitive data that should be redacted from output
SENSITIVE_PATTERNS = [
    r'sk-[a-zA-Z0-9]{20,}',  # Anthropic API keys
    r'ANTHROPIC_API_KEY=[^\s]+',
    r'api[_-]?key[=:][^\s]+',
    r'token[=:][^\s]+',
    r'password[=:][^\s]+',
    r'secret[=:][^\s]+',
]


def sanitize_output(line: str) -> str:
    """Remove sensitive information from output lines."""
    for pattern in SENSITIVE_PATTERNS:
        line = re.sub(pattern, '[REDACTED]', line, flags=re.IGNORECASE)
    return line


class ContainerManager:
    """
    Manages a Docker container for a single project.

    Container lifecycle:
    - not_created: Project exists but container never started
    - running: Container is running, Claude Code is active
    - stopped: Container stopped (idle timeout or manual), can restart quickly
    """

    def __init__(
        self,
        project_name: str,
        project_dir: Path,
        claude_credentials_dir: Path | None = None,
    ):
        """
        Initialize the container manager.

        Args:
            project_name: Name of the project
            project_dir: Absolute path to the project directory
            claude_credentials_dir: Path to Claude credentials (~/.claude)
        """
        self.project_name = project_name
        self.project_dir = project_dir
        self.claude_credentials_dir = claude_credentials_dir or Path.home() / ".claude"
        self.container_name = f"autocoder-{project_name}"

        self._status: Literal["not_created", "running", "stopped"] = "not_created"
        self.started_at: datetime | None = None
        self.last_activity: datetime | None = None
        self._log_task: asyncio.Task | None = None

        # Callbacks for WebSocket notifications
        self._output_callbacks: Set[Callable[[str], Awaitable[None]]] = set()
        self._status_callbacks: Set[Callable[[str], Awaitable[None]]] = set()
        self._callbacks_lock = threading.Lock()

        # Check initial container status
        self._sync_status()

    def _sync_status(self) -> None:
        """Sync status with actual Docker container state."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", self.container_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                docker_status = result.stdout.strip()
                if docker_status == "running":
                    self._status = "running"
                else:
                    self._status = "stopped"
            else:
                self._status = "not_created"
        except Exception as e:
            logger.warning(f"Failed to check container status: {e}")
            self._status = "not_created"

    @property
    def status(self) -> Literal["not_created", "running", "stopped"]:
        return self._status

    @status.setter
    def status(self, value: Literal["not_created", "running", "stopped"]):
        old_status = self._status
        self._status = value
        if old_status != value:
            self._notify_status_change(value)

    def _notify_status_change(self, status: str) -> None:
        """Notify all registered callbacks of status change."""
        with self._callbacks_lock:
            callbacks = list(self._status_callbacks)

        for callback in callbacks:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._safe_callback(callback, status))
            except RuntimeError:
                pass

    async def _safe_callback(self, callback: Callable, *args) -> None:
        """Safely execute a callback, catching and logging any errors."""
        try:
            await callback(*args)
        except Exception as e:
            logger.warning(f"Callback error: {e}")

    def add_output_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Add a callback for output lines."""
        with self._callbacks_lock:
            self._output_callbacks.add(callback)

    def remove_output_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Remove an output callback."""
        with self._callbacks_lock:
            self._output_callbacks.discard(callback)

    def add_status_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Add a callback for status changes."""
        with self._callbacks_lock:
            self._status_callbacks.add(callback)

    def remove_status_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Remove a status callback."""
        with self._callbacks_lock:
            self._status_callbacks.discard(callback)

    def _update_activity(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.now()

    def is_idle(self) -> bool:
        """Check if container has been idle for longer than timeout."""
        if self.last_activity is None:
            return False
        idle_duration = datetime.now() - self.last_activity
        return idle_duration > timedelta(minutes=IDLE_TIMEOUT_MINUTES)

    def get_idle_seconds(self) -> int:
        """Get seconds since last activity."""
        if self.last_activity is None:
            return 0
        return int((datetime.now() - self.last_activity).total_seconds())

    async def _broadcast_output(self, line: str) -> None:
        """Broadcast output line to all registered callbacks."""
        with self._callbacks_lock:
            callbacks = list(self._output_callbacks)

        for callback in callbacks:
            await self._safe_callback(callback, line)

    async def _stream_logs(self) -> None:
        """Stream container logs to callbacks."""
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "logs", "-f", "--tail", "0", self.container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            while True:
                if process.stdout is None:
                    break

                line = await process.stdout.readline()
                if not line:
                    break

                decoded = line.decode("utf-8", errors="replace").rstrip()
                sanitized = sanitize_output(decoded)

                self._update_activity()
                await self._broadcast_output(sanitized)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Log streaming error: {e}")

    async def start(self, instruction: str | None = None) -> tuple[bool, str]:
        """
        Start or restart the container and optionally send an instruction.

        Args:
            instruction: Optional instruction to send to Claude Code

        Returns:
            Tuple of (success, message)
        """
        self._sync_status()

        if self._status == "running":
            # Container already running, just send instruction if provided
            if instruction:
                return await self.send_instruction(instruction)
            return True, "Container already running"

        try:
            if self._status == "stopped":
                # Restart existing container
                result = subprocess.run(
                    ["docker", "start", self.container_name],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    return False, f"Failed to start container: {result.stderr}"
            else:
                # Create new container
                # Mount credentials to temp location (entrypoint copies to coder home)
                cmd = [
                    "docker", "run", "-d",
                    "--name", self.container_name,
                    "-v", f"{self.project_dir}:/project",
                    "-v", f"{self.claude_credentials_dir}:/tmp/claude-creds:ro",
                    "-e", "ANTHROPIC_API_KEY",  # Pass through from host
                    CONTAINER_IMAGE,
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    return False, f"Failed to create container: {result.stderr}"

            self.started_at = datetime.now()
            self._update_activity()
            self.status = "running"

            # Start log streaming
            self._log_task = asyncio.create_task(self._stream_logs())

            # Send instruction if provided
            if instruction:
                # Wait for claude to be available (entrypoint runs npm update)
                for attempt in range(10):
                    await asyncio.sleep(2)
                    check = subprocess.run(
                        ["docker", "exec", "-u", "coder", self.container_name,
                         "which", "claude"],
                        capture_output=True,
                        text=True,
                    )
                    if check.returncode == 0:
                        break
                    logger.info(f"Waiting for claude to be ready (attempt {attempt + 1}/10)")
                else:
                    return False, "Claude Code not available in container after 20 seconds"

                return await self.send_instruction(instruction)

            return True, f"Container {self.container_name} started"

        except Exception as e:
            logger.exception("Failed to start container")
            return False, f"Failed to start container: {e}"

    async def stop(self) -> tuple[bool, str]:
        """
        Stop the container (don't remove it).

        Returns:
            Tuple of (success, message)
        """
        self._sync_status()

        if self._status != "running":
            return False, "Container is not running"

        try:
            # Cancel log streaming
            if self._log_task:
                self._log_task.cancel()
                try:
                    await self._log_task
                except asyncio.CancelledError:
                    pass

            result = subprocess.run(
                ["docker", "stop", self.container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return False, f"Failed to stop container: {result.stderr}"

            self.status = "stopped"
            return True, f"Container {self.container_name} stopped"

        except subprocess.TimeoutExpired:
            # Force kill
            subprocess.run(
                ["docker", "kill", self.container_name],
                capture_output=True
            )
            self.status = "stopped"
            return True, f"Container {self.container_name} killed (timeout)"
        except Exception as e:
            logger.exception("Failed to stop container")
            return False, f"Failed to stop container: {e}"

    async def send_instruction(self, instruction: str) -> tuple[bool, str]:
        """
        Send an instruction to Claude Code running in the container.

        Args:
            instruction: The instruction/prompt to send

        Returns:
            Tuple of (success, message)
        """
        self._sync_status()

        if self._status != "running":
            return False, "Container is not running"

        try:
            self._update_activity()

            # Use docker exec to run claude with the instruction
            # Run as 'coder' user (non-root) to allow --dangerously-skip-permissions
            # --dangerously-skip-permissions allows autonomous operation in sandbox
            # --print outputs response without interactive mode
            process = await asyncio.create_subprocess_exec(
                "docker", "exec", "-u", "coder", self.container_name,
                "claude", "--print", "--dangerously-skip-permissions", instruction,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            # Stream output to callbacks
            while True:
                if process.stdout is None:
                    break
                line = await process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                sanitized = sanitize_output(decoded)
                self._update_activity()
                await self._broadcast_output(sanitized)

            await process.wait()

            return True, "Instruction sent"

        except Exception as e:
            logger.exception("Failed to send instruction")
            return False, f"Failed to send instruction: {e}"

    async def remove(self) -> tuple[bool, str]:
        """
        Remove the container completely.

        Returns:
            Tuple of (success, message)
        """
        # Stop first if running
        if self._status == "running":
            await self.stop()

        try:
            result = subprocess.run(
                ["docker", "rm", self.container_name],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                if "No such container" in result.stderr:
                    self.status = "not_created"
                    return True, "Container already removed"
                return False, f"Failed to remove container: {result.stderr}"

            self.status = "not_created"
            return True, f"Container {self.container_name} removed"

        except Exception as e:
            logger.exception("Failed to remove container")
            return False, f"Failed to remove container: {e}"

    def get_status_dict(self) -> dict:
        """Get current status as a dictionary."""
        self._sync_status()
        return {
            "status": self.status,
            "container_name": self.container_name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "idle_seconds": self.get_idle_seconds(),
        }


# Global registry of container managers per project
_managers: dict[str, ContainerManager] = {}
_managers_lock = threading.Lock()


def get_container_manager(
    project_name: str,
    project_dir: Path,
    claude_credentials_dir: Path | None = None,
) -> ContainerManager:
    """Get or create a container manager for a project (thread-safe)."""
    with _managers_lock:
        if project_name not in _managers:
            _managers[project_name] = ContainerManager(
                project_name, project_dir, claude_credentials_dir
            )
        return _managers[project_name]


async def cleanup_idle_containers() -> list[str]:
    """
    Stop containers that have been idle for longer than the timeout.

    Returns:
        List of container names that were stopped
    """
    stopped = []

    with _managers_lock:
        managers = list(_managers.values())

    for manager in managers:
        if manager.status == "running" and manager.is_idle():
            success, _ = await manager.stop()
            if success:
                stopped.append(manager.container_name)
                logger.info(f"Stopped idle container: {manager.container_name}")

    return stopped


async def cleanup_all_containers() -> None:
    """Stop all running containers. Called on server shutdown."""
    logger.info("Stopping all autocoder containers...")

    with _managers_lock:
        managers = list(_managers.values())

    for manager in managers:
        try:
            if manager.status == "running":
                logger.info(f"Stopping container: {manager.container_name}")
                await manager.stop()
        except Exception as e:
            logger.warning(f"Error stopping container for {manager.project_name}: {e}")

    # Also stop any orphaned containers not in our registry
    await stop_orphaned_containers()

    with _managers_lock:
        _managers.clear()


async def stop_orphaned_containers() -> None:
    """Stop any autocoder-* containers not tracked in our registry."""
    try:
        # List all containers with autocoder- prefix
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter", "name=autocoder-"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            container_ids = result.stdout.strip().split("\n")
            for container_id in container_ids:
                if container_id:
                    logger.info(f"Stopping orphaned container: {container_id}")
                    subprocess.run(
                        ["docker", "stop", container_id],
                        capture_output=True,
                        timeout=10,
                    )
    except Exception as e:
        logger.warning(f"Error stopping orphaned containers: {e}")


def check_docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def check_image_exists() -> bool:
    """Check if the project container image exists."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", CONTAINER_IMAGE],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False
