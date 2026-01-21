"""Docker-based sandbox for safe code execution"""

import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

import docker
from docker.errors import ContainerError, ImageNotFound, APIError

from src.config import settings
from src.config.exception_config import SandboxExecutionError

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of sandbox execution"""

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int = 0


class DockerSandbox:
    """
    Docker-based sandbox for executing code in isolation.

    Supports Node.js, Python, and other runtime environments.
    """

    # Base images for different project types
    IMAGES = {
        "nodejs": "node:20-slim",
        "python": "python:3.12-slim",
        "rust": "rust:1.75-slim",
        "go": "golang:1.21-alpine",
    }

    def __init__(self):
        """Initialize Docker client"""
        try:
            self.client = docker.from_env()
            self.client.ping()
            logger.info("Docker client initialized successfully")
        except Exception as e:
            logger.warning(f"Docker not available: {e}")
            self.client = None

    def is_available(self) -> bool:
        """Check if Docker is available"""
        return self.client is not None

    async def execute(
        self,
        project_dir: str,
        command: str,
        project_type: str = "nodejs",
        timeout: Optional[int] = None,
    ) -> ExecutionResult:
        """
        Execute a command in a Docker container.

        Args:
            project_dir: Path to the project directory to mount
            command: Command to execute
            project_type: Type of project (nodejs, python, etc.)
            timeout: Execution timeout in seconds

        Returns:
            ExecutionResult with output and status
        """
        if not self.is_available():
            raise SandboxExecutionError("Docker is not available")

        timeout = timeout or settings.sandbox_timeout
        image = self.IMAGES.get(project_type, "ubuntu:22.04")

        # Ensure image is available
        await self._ensure_image(image)

        logger.info(f"Executing in sandbox: {command}")

        try:
            import time
            start_time = time.time()

            container = self.client.containers.run(
                image=image,
                command=f"sh -c '{command}'",
                volumes={
                    os.path.abspath(project_dir): {
                        "bind": "/app",
                        "mode": "rw",
                    }
                },
                working_dir="/app",
                mem_limit=settings.sandbox_memory_limit,
                cpu_quota=int(settings.sandbox_cpu_limit * 100000),
                network_mode="bridge",  # Allow network for npm install etc.
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
                timeout=timeout,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # container.run returns bytes when detach=False
            output = container.decode("utf-8") if isinstance(container, bytes) else str(container)

            return ExecutionResult(
                success=True,
                exit_code=0,
                stdout=output,
                stderr="",
                duration_ms=duration_ms,
            )

        except ContainerError as e:
            logger.warning(f"Container execution failed: {e}")
            return ExecutionResult(
                success=False,
                exit_code=e.exit_status,
                stdout=e.stderr.decode("utf-8") if e.stderr else "",
                stderr=str(e),
            )

        except Exception as e:
            logger.exception(f"Sandbox execution error: {e}")
            raise SandboxExecutionError(f"Execution failed: {str(e)}")

    async def _ensure_image(self, image: str) -> None:
        """Ensure Docker image is available, pull if necessary"""
        try:
            self.client.images.get(image)
        except ImageNotFound:
            logger.info(f"Pulling image: {image}")
            try:
                self.client.images.pull(image)
            except APIError as e:
                raise SandboxExecutionError(f"Failed to pull image {image}: {e}")

    async def run_tests(
        self,
        project_dir: str,
        test_code: str,
        project_type: str = "nodejs",
    ) -> ExecutionResult:
        """
        Run generated test code in the sandbox.

        Args:
            project_dir: Path to the project directory
            test_code: Generated test code to execute
            project_type: Type of project

        Returns:
            ExecutionResult with test output
        """
        # Write test file
        test_file = self._get_test_filename(project_type)
        test_path = os.path.join(project_dir, test_file)

        with open(test_path, "w") as f:
            f.write(test_code)

        # Get test command
        test_command = self._get_test_command(project_type)

        # First install dependencies
        install_command = self._get_install_command(project_type)
        if install_command:
            install_result = await self.execute(
                project_dir=project_dir,
                command=install_command,
                project_type=project_type,
                timeout=120,
            )
            if not install_result.success:
                logger.warning(f"Dependency installation failed: {install_result.stderr}")

        # Run tests
        return await self.execute(
            project_dir=project_dir,
            command=test_command,
            project_type=project_type,
        )

    def _get_test_filename(self, project_type: str) -> str:
        """Get test filename for project type"""
        filenames = {
            "nodejs": "generated.test.js",
            "python": "test_generated.py",
            "rust": "generated_test.rs",
            "go": "generated_test.go",
        }
        return filenames.get(project_type, "test_generated.txt")

    def _get_test_command(self, project_type: str) -> str:
        """Get test command for project type"""
        commands = {
            "nodejs": "npm test || npx jest generated.test.js || node generated.test.js",
            "python": "pytest test_generated.py -v || python test_generated.py",
            "rust": "cargo test",
            "go": "go test -v ./...",
        }
        return commands.get(project_type, "echo 'Unknown project type'")

    def _get_install_command(self, project_type: str) -> Optional[str]:
        """Get dependency install command for project type"""
        commands = {
            "nodejs": "npm install --legacy-peer-deps",
            "python": "pip install -r requirements.txt || pip install pytest",
            "rust": "cargo build",
            "go": "go mod download",
        }
        return commands.get(project_type)
