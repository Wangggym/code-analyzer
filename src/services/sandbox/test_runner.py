"""Test generation and execution service"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Callable

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from src.config import settings
from src.services.startup_analyzer import StartupConfig, analyze_startup_method
from src.services.sandbox.project_runner import ProjectRunner, RunningProject
from src.services.sse_helper import SSEEvent, Stages
from src.schema.response import (
    FeatureAnalysis,
    FunctionalVerification,
    ExecutionResult as SchemaExecutionResult,
)

logger = logging.getLogger(__name__)

# Type for progress callback
ProgressCallback = Callable[[SSEEvent], None]


@dataclass
class TestGenerationResult:
    """Result of test generation"""

    test_code: str
    language: str
    framework: str


# System prompt for test generation
TEST_GENERATION_PROMPT = """You are an expert test engineer. Generate functional tests that verify the features work correctly.

Given:
1. Problem description with required features
2. Analysis of where features are implemented
3. API information (type, port, endpoints)

Generate test code that:
1. Tests each feature end-to-end via API calls
2. Uses appropriate testing patterns
3. Is self-contained and runnable

For GraphQL APIs (Node.js):
- Use native fetch (available in Node.js 18+)
- Test mutations and queries
- Include proper async/await
- Print clear test results

For REST APIs:
- Test CRUD operations
- Verify response status and data

Output ONLY the test code, no explanations. The code must be runnable with Node.js 18+ (using native fetch).

Example format for GraphQL:
```javascript
const BASE_URL = 'http://localhost:3000/graphql';

async function graphql(query, variables = {}) {
  const res = await fetch(BASE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, variables })
  });
  return res.json();
}

async function runTests() {
  console.log('=== Starting Functional Tests ===\\n');
  
  // Test 1: Create Channel
  console.log('Test 1: Create Channel');
  const createRes = await graphql(`
    mutation { createChannel(createChannelInput: { name: "Test Channel" }) { id name } }
  `);
  if (!createRes.data?.createChannel?.id) {
    throw new Error('Create channel failed: ' + JSON.stringify(createRes));
  }
  const channelId = createRes.data.createChannel.id;
  console.log('✓ Created channel with id:', channelId);
  
  // Test 2: Create Message
  console.log('\\nTest 2: Create Message');
  const msgRes = await graphql(`
    mutation { createMessage(createMessageInput: { channelId: ${channelId}, title: "Test", content: "Hello" }) { id title content } }
  `);
  if (!msgRes.data?.createMessage?.id) {
    throw new Error('Create message failed: ' + JSON.stringify(msgRes));
  }
  console.log('✓ Created message');
}

runTests()
  .then(() => {
    console.log('\\n=== All Tests Passed ===');
    process.exit(0);
  })
  .catch(err => {
    console.error('\\n=== Test Failed ===');
    console.error(err.message);
    process.exit(1);
  });
```
"""


class TestRunner:
    """
    Service for generating and running functional tests.

    Flow:
    1. Analyze startup method (LLM)
    2. Start project in Docker
    3. Generate test code (LLM)
    4. Execute tests
    5. Collect results
    6. Stop and cleanup project
    """

    def __init__(self):
        self.project_runner = ProjectRunner()

    async def run_functional_verification(
        self,
        problem_description: str,
        feature_analysis: list[FeatureAnalysis],
        project_dir: str,
        on_progress: ProgressCallback | None = None,
    ) -> FunctionalVerification:
        """
        Run complete functional verification.

        Args:
            problem_description: Original feature requirements
            feature_analysis: List of analyzed features
            project_dir: Path to project directory
            on_progress: Optional callback for progress updates

        Returns:
            FunctionalVerification with test code and results

        Raises:
            RuntimeError: If verification fails
        """
        project: RunningProject | None = None

        def emit(stage: str, message: str) -> None:
            """Helper to emit progress"""
            if on_progress:
                on_progress(SSEEvent(stage=stage, message=message))
            logger.info(f"[{stage}] {message}")

        try:
            # Step 1: Analyze startup method
            emit(Stages.ANALYZING_STARTUP, "Analyzing how to start the project...")
            startup_config = await analyze_startup_method(project_dir)
            emit(
                Stages.ANALYZING_STARTUP,
                f"Using {startup_config.start_method} with {startup_config.runtime}: {startup_config.reason}",
            )

            if startup_config.start_method == "unknown":
                raise RuntimeError("Could not determine how to start the project")

            # Step 2: Start project
            emit(Stages.STARTING_PROJECT, "Starting project in Docker sandbox...")
            project = await self.project_runner.start_project(project_dir, startup_config)

            emit(Stages.WAITING_HEALTH, "Waiting for service to be ready...")
            # Health check is done inside start_project
            emit(Stages.WAITING_HEALTH, f"Service is running on port {startup_config.service_port}")

            # Step 3: Generate test code
            emit(Stages.GENERATING_TESTS, "Generating test code with AI...")
            test_result = await self._generate_tests(
                problem_description=problem_description,
                feature_analysis=feature_analysis,
                startup_config=startup_config,
            )
            emit(Stages.GENERATING_TESTS, f"Generated {len(test_result.test_code)} bytes of test code")

            # Step 4: Execute tests
            emit(Stages.RUNNING_TESTS, "Executing tests...")
            execution_result = await self._execute_tests(
                test_code=test_result.test_code,
                startup_config=startup_config,
                container_name=project.container_name,
            )

            passed = execution_result["passed"]
            emit(
                Stages.RUNNING_TESTS,
                f"Tests {'passed' if passed else 'failed'}",
            )

            return FunctionalVerification(
                generated_test_code=test_result.test_code,
                execution_result=SchemaExecutionResult(
                    tests_passed=execution_result["passed"],
                    log=execution_result["log"],
                ),
            )

        finally:
            # Step 5: Cleanup
            if project:
                emit(Stages.CLEANUP, "Stopping project and cleaning up...")
                await self.project_runner.stop_project(project)
                emit(Stages.CLEANUP, "Cleanup complete")

    async def _generate_tests(
        self,
        problem_description: str,
        feature_analysis: list[FeatureAnalysis],
        startup_config: StartupConfig,
    ) -> TestGenerationResult:
        """Generate test code using LLM"""
        # Format feature analysis for prompt
        features_text = "\n".join(
            f"- {f.feature_description}: {', '.join(loc.file + ':' + loc.function for loc in f.implementation_location)}"
            for f in feature_analysis
        )

        # Determine API type
        api_info = f"""
API Type: GraphQL (based on project structure)
Service Port: {startup_config.service_port}
Base URL: http://localhost:{startup_config.service_port}
GraphQL Endpoint: http://localhost:{startup_config.service_port}/graphql
"""

        user_prompt = f"""## Problem Description
{problem_description}

## Feature Analysis
{features_text}

## API Information
{api_info}

Generate functional test code to verify these features work correctly.
The tests should make real HTTP requests to the running service.
Use native fetch (Node.js 18+), no external dependencies.
"""

        provider = AnthropicProvider(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
        )
        model = AnthropicModel(
            model_name=settings.anthropic_model_id,
            provider=provider,
        )

        agent = Agent(model=model, system_prompt=TEST_GENERATION_PROMPT)

        result = await agent.run(user_prompt)
        test_code = result.output

        # Clean up code blocks if present
        if "```javascript" in test_code:
            start = test_code.find("```javascript") + 13
            end = test_code.find("```", start)
            test_code = test_code[start:end].strip()
        elif "```js" in test_code:
            start = test_code.find("```js") + 5
            end = test_code.find("```", start)
            test_code = test_code[start:end].strip()
        elif "```" in test_code:
            start = test_code.find("```") + 3
            end = test_code.find("```", start)
            test_code = test_code[start:end].strip()

        return TestGenerationResult(
            test_code=test_code,
            language="javascript",
            framework="native-fetch",
        )

    async def _execute_tests(
        self,
        test_code: str,
        startup_config: StartupConfig,
        container_name: str,
    ) -> dict:
        """Execute test code inside the sandbox container"""
        import tempfile
        import uuid

        # Create temp file for test
        test_filename = f"test_{uuid.uuid4().hex[:8]}.mjs"
        local_test_file = None

        try:
            # Write test code to a temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".mjs", delete=False
            ) as f:
                f.write(test_code)
                local_test_file = f.name

            # Copy test file to the container
            container_test_path = f"/tmp/{test_filename}"
            copy_cmd = f"docker cp {local_test_file} {container_name}:{container_test_path}"

            proc = await asyncio.create_subprocess_shell(
                copy_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            if proc.returncode != 0:
                return {
                    "passed": False,
                    "log": f"Failed to copy test file to container",
                }

            # Execute test inside the container
            # Use localhost since we're inside the container now
            exec_cmd = f"docker exec {container_name} node {container_test_path}"
            logger.info(f"Executing tests: {exec_cmd}")

            proc = await asyncio.create_subprocess_shell(
                exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=60
                )
                stdout_str = stdout.decode("utf-8", errors="ignore")
                stderr_str = stderr.decode("utf-8", errors="ignore")

                log = stdout_str
                if stderr_str:
                    log += "\n" + stderr_str

                passed = proc.returncode == 0

                return {
                    "passed": passed,
                    "log": log.strip() or "(no output)",
                }

            except asyncio.TimeoutError:
                proc.kill()
                return {
                    "passed": False,
                    "log": "Test execution timeout (60s)",
                }

        finally:
            # Cleanup local temp file
            if local_test_file:
                try:
                    os.unlink(local_test_file)
                except Exception:
                    pass
            # Cleanup container test file
            try:
                cleanup_cmd = f"docker exec {container_name} rm -f {container_test_path}"
                proc = await asyncio.create_subprocess_shell(
                    cleanup_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
            except Exception:
                pass
