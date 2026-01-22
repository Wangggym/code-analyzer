"""Project runner for starting/stopping projects in isolation"""

import asyncio
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass

import httpx

from src.services.startup_analyzer import StartupConfig

logger = logging.getLogger(__name__)

# Timeout for startup (seconds)
STARTUP_TIMEOUT = 120


@dataclass
class RunningProject:
    """Information about a running project"""

    project_id: str
    project_dir: str
    config: StartupConfig
    is_running: bool = False


class ProjectRunner:
    """
    Manages project lifecycle: start, health check, stop.

    Uses Docker or native runtime based on StartupConfig.
    """

    def __init__(self):
        self.running_projects: dict[str, RunningProject] = {}

    async def start_project(
        self, project_dir: str, config: StartupConfig
    ) -> RunningProject:
        """
        Start the project based on the startup configuration.

        Args:
            project_dir: Path to the project directory
            config: Startup configuration from LLM analysis

        Returns:
            RunningProject instance

        Raises:
            RuntimeError: If project fails to start
        """
        project_id = str(uuid.uuid4())[:8]
        project = RunningProject(
            project_id=project_id,
            project_dir=project_dir,
            config=config,
        )

        logger.info(f"Starting project {project_id} with method: {config.start_method}")

        try:
            if config.start_method == "docker-compose":
                await self._start_docker_compose(project)
            elif config.start_method == "dockerfile":
                await self._start_dockerfile(project)
            elif config.start_method in ("npm", "python"):
                await self._start_native(project)
            else:
                raise RuntimeError(f"Unknown start method: {config.start_method}")

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
        Stop and cleanup the project.

        Args:
            project: The running project to stop
        """
        logger.info(f"Stopping project {project.project_id}")

        try:
            config = project.config
            working_dir = os.path.join(project.project_dir, config.working_dir)

            if config.start_method == "docker-compose":
                # Use project-specific name for isolation
                cmd = f"docker-compose -p ca-{project.project_id} down -v --remove-orphans"
                await self._run_command(cmd, working_dir, timeout=60)

            elif config.start_method == "dockerfile":
                container_name = f"ca-{project.project_id}"
                await self._run_command(f"docker rm -f {container_name}", working_dir, timeout=30)

            elif config.stop_command:
                await self._run_command(config.stop_command, working_dir, timeout=30)

        except Exception as e:
            logger.warning(f"Error stopping project {project.project_id}: {e}")

        finally:
            project.is_running = False
            self.running_projects.pop(project.project_id, None)

    async def _start_docker_compose(self, project: RunningProject) -> None:
        """Start project using docker-compose"""
        config = project.config
        working_dir = os.path.join(project.project_dir, config.working_dir)

        # Use project-specific name for isolation
        project_name = f"ca-{project.project_id}"

        # Check for compose file
        compose_file = None
        for name in ["docker-compose.yml", "docker-compose.yaml"]:
            if os.path.exists(os.path.join(working_dir, name)):
                compose_file = name
                break

        if not compose_file:
            raise RuntimeError("docker-compose.yml not found")

        # Copy .env.example to .env if needed
        env_example = os.path.join(working_dir, ".env.example")
        env_file = os.path.join(working_dir, ".env")
        if os.path.exists(env_example) and not os.path.exists(env_file):
            import shutil
            shutil.copy(env_example, env_file)

        # Also check for .env.compose.example
        env_compose_example = os.path.join(working_dir, ".env.compose.example")
        if os.path.exists(env_compose_example) and not os.path.exists(env_file):
            import shutil
            shutil.copy(env_compose_example, env_file)

        # Build and start
        cmd = f"docker-compose -p {project_name} -f {compose_file} up -d --build"
        await self._run_command(cmd, working_dir, timeout=STARTUP_TIMEOUT)

    async def _start_dockerfile(self, project: RunningProject) -> None:
        """Start project using Dockerfile"""
        config = project.config
        working_dir = os.path.join(project.project_dir, config.working_dir)
        container_name = f"ca-{project.project_id}"
        image_name = f"ca-image-{project.project_id}"

        # Build image
        build_cmd = f"docker build -t {image_name} ."
        await self._run_command(build_cmd, working_dir, timeout=STARTUP_TIMEOUT)

        # Run container
        port = config.service_port
        run_cmd = f"docker run -d --name {container_name} -p {port}:{port} {image_name}"
        await self._run_command(run_cmd, working_dir, timeout=30)

    async def _start_native(self, project: RunningProject) -> None:
        """Start project using native runtime (npm/python) in Docker"""
        config = project.config
        working_dir = os.path.join(project.project_dir, config.working_dir)
        container_name = f"ca-{project.project_id}"
        port = config.service_port

        if config.start_method == "npm":
            image = "node:20-slim"
            cmd = config.start_command or "npm install && npm start"
        else:
            image = "python:3.12-slim"
            cmd = config.start_command or "pip install -r requirements.txt && python main.py"

        # Run in detached container
        docker_cmd = (
            f"docker run -d --name {container_name} "
            f"-p {port}:{port} "
            f"-v {working_dir}:/app "
            f"-w /app "
            f"{image} "
            f"sh -c '{cmd}'"
        )
        await self._run_command(docker_cmd, working_dir, timeout=STARTUP_TIMEOUT)

    async def _wait_for_health(self, project: RunningProject) -> None:
        """Wait for project to be healthy"""
        config = project.config
        health_url = config.health_check_url

        if not health_url:
            # Default: just wait estimated time
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
                    raise RuntimeError(f"Health check timeout after {timeout}s")

                try:
                    response = await client.get(health_url)
                    if response.status_code < 500:
                        logger.info(f"Health check passed: {response.status_code}")
                        return
                except Exception as e:
                    logger.debug(f"Health check failed: {e}")

                await asyncio.sleep(2)

    async def _run_command(
        self, cmd: str, cwd: str, timeout: int = 60
    ) -> tuple[str, str]:
        """Run a shell command"""
        logger.debug(f"Running command: {cmd}")

        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            stdout_str = stdout.decode("utf-8", errors="ignore")
            stderr_str = stderr.decode("utf-8", errors="ignore")

            if proc.returncode != 0:
                logger.warning(f"Command failed: {stderr_str}")

            return stdout_str, stderr_str

        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Command timeout after {timeout}s: {cmd}")
