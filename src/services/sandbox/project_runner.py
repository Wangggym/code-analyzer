"""Project runner for starting/stopping projects in Docker sandbox"""

import asyncio
import logging
import uuid
from dataclasses import dataclass

import httpx

from src.services.startup_analyzer import StartupConfig

logger = logging.getLogger(__name__)

# Timeout for startup (seconds) - npm install can take 90s+
STARTUP_TIMEOUT = 180


@dataclass
class RunningProject:
    """Information about a running project"""

    project_id: str
    container_name: str
    project_dir: str
    config: StartupConfig
    is_running: bool = False


class ProjectRunner:
    """
    Manages project lifecycle: start, health check, stop.

    All projects run in Docker containers for isolation.
    """

    def __init__(self):
        self.running_projects: dict[str, RunningProject] = {}

    async def start_project(
        self, project_dir: str, config: StartupConfig
    ) -> RunningProject:
        """
        Start the project in a Docker container.

        Args:
            project_dir: Path to the project directory
            config: Startup configuration from LLM analysis

        Returns:
            RunningProject instance

        Raises:
            RuntimeError: If project fails to start
        """
        project_id = str(uuid.uuid4())[:8]
        container_name = f"ca-{project_id}"

        project = RunningProject(
            project_id=project_id,
            container_name=container_name,
            project_dir=project_dir,
            config=config,
        )

        logger.info(
            f"Starting project {project_id} "
            f"method={config.start_method} "
            f"runtime={config.runtime} "
            f"reason={config.reason}"
        )

        try:
            # Build the startup command
            if config.install_command and config.start_command:
                cmd = f"{config.install_command} && {config.start_command}"
            elif config.start_command:
                cmd = config.start_command
            else:
                raise RuntimeError("No start command provided")

            port = config.service_port

            # Run in Docker container
            docker_cmd = (
                f"docker run -d "
                f"--name {container_name} "
                f"-p {port}:{port} "
                f"-v {project_dir}:/app "
                f"-w /app "
                f"{config.runtime} "
                f'sh -c "{cmd}"'
            )

            logger.info(f"Docker command: {docker_cmd}")

            # Start container
            stdout, stderr = await self._run_command(docker_cmd, timeout=60)
            container_id = stdout.strip()

            if not container_id:
                raise RuntimeError(f"Failed to start container: {stderr}")

            logger.info(f"Container started: {container_id[:12]}")

            # Wait for health check
            await self._wait_for_health(project)

            project.is_running = True
            self.running_projects[project_id] = project

            logger.info(f"Project {project_id} started successfully")
            return project

        except Exception as e:
            # Cleanup on failure
            await self.stop_project(project)
            raise RuntimeError(f"Failed to start project: {e}")

    async def stop_project(self, project: RunningProject) -> None:
        """
        Stop and cleanup the project container.

        Args:
            project: The running project to stop
        """
        logger.info(f"Stopping project {project.project_id}")

        try:
            # Force remove container
            cmd = f"docker rm -f {project.container_name}"
            await self._run_command(cmd, timeout=30)
            logger.info(f"Container {project.container_name} removed")

        except Exception as e:
            logger.warning(f"Error stopping project {project.project_id}: {e}")

        finally:
            project.is_running = False
            self.running_projects.pop(project.project_id, None)

    async def get_container_logs(self, project: RunningProject) -> str:
        """Get logs from the project container"""
        try:
            cmd = f"docker logs {project.container_name} 2>&1"
            stdout, _ = await self._run_command(cmd, timeout=10)
            return stdout
        except Exception as e:
            return f"Failed to get logs: {e}"

    async def _wait_for_health(self, project: RunningProject) -> None:
        """Wait for project to be healthy"""
        config = project.config
        health_url = config.health_check_url

        if not health_url:
            # No health check URL, just wait estimated time
            logger.info(f"No health check URL, waiting {config.estimated_startup_time}s")
            await asyncio.sleep(config.estimated_startup_time)
            return

        logger.info(f"Waiting for health check: {health_url}")

        start_time = asyncio.get_event_loop().time()
        timeout = STARTUP_TIMEOUT

        async with httpx.AsyncClient(timeout=5) as client:
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    # Get logs for debugging
                    logs = await self.get_container_logs(project)
                    logger.error(f"Container logs:\n{logs[-2000:]}")
                    raise RuntimeError(f"Health check timeout after {timeout}s")

                try:
                    response = await client.get(health_url)
                    if response.status_code < 500:
                        logger.info(f"Health check passed: {response.status_code}")
                        return
                except Exception as e:
                    logger.debug(f"Health check failed ({int(elapsed)}s): {e}")

                await asyncio.sleep(3)

    async def _run_command(self, cmd: str, timeout: int = 60) -> tuple[str, str]:
        """Run a shell command"""
        logger.debug(f"Running: {cmd}")

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout_str = stdout.decode("utf-8", errors="ignore")
            stderr_str = stderr.decode("utf-8", errors="ignore")

            if proc.returncode != 0:
                logger.warning(f"Command failed (exit {proc.returncode}): {stderr_str}")

            return stdout_str, stderr_str

        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Command timeout after {timeout}s: {cmd}")
