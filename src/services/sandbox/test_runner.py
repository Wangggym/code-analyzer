"""Test generation and execution service"""

import asyncio
import logging
import os
from dataclasses import dataclass

import httpx
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from src.config import settings
from src.services.startup_analyzer import StartupConfig, analyze_startup_method
from src.services.sandbox.project_runner import ProjectRunner, RunningProject
from src.schema.response import (
    FeatureAnalysis,
    FunctionalVerification,
    ExecutionResult as SchemaExecutionResult,
)

logger = logging.getLogger(__name__)


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
- Use fetch or axios for HTTP requests
- Test mutations and queries
- Include proper async/await

For REST APIs:
- Test CRUD operations
- Verify response status and data

Output ONLY the test code, no explanations. The code must be runnable with Node.js (using fetch).

Example format for GraphQL:
```javascript
const BASE_URL = 'http://localhost:3000/graphql';

async function test() {
  console.log('Testing: Create channel...');
  const createRes = await fetch(BASE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: `mutation { createChannel(createChannelInput: { name: "Test" }) { id name } }`
    })
  });
  const createData = await createRes.json();
  console.log('Result:', JSON.stringify(createData, null, 2));
  
  if (!createData.data?.createChannel?.id) {
    throw new Error('Create channel failed');
  }
  console.log('✓ Create channel passed');
}

test().then(() => {
  console.log('\\n✓ All tests passed!');
  process.exit(0);
}).catch(err => {
  console.error('\\n✗ Test failed:', err.message);
  process.exit(1);
});
```
"""


class TestRunner:
    """
    Service for generating and running functional tests.

    Flow:
    1. Analyze startup method (LLM)
    2. Start project in isolation
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
    ) -> FunctionalVerification:
        """
        Run complete functional verification.

        Args:
            problem_description: Original feature requirements
            feature_analysis: List of analyzed features
            project_dir: Path to project directory

        Returns:
            FunctionalVerification with test code and results

        Raises:
            RuntimeError: If verification fails
        """
        project: RunningProject | None = None

        try:
            # Step 1: Analyze startup method
            logger.info("Step 1: Analyzing startup method...")
            startup_config = await analyze_startup_method(project_dir)
            logger.info(f"Startup config: {startup_config.start_method}")

            if startup_config.start_method == "unknown":
                raise RuntimeError("Could not determine how to start the project")

            # Step 2: Start project
            logger.info("Step 2: Starting project...")
            project = await self.project_runner.start_project(project_dir, startup_config)

            # Step 3: Generate test code
            logger.info("Step 3: Generating test code...")
            test_result = await self._generate_tests(
                problem_description=problem_description,
                feature_analysis=feature_analysis,
                startup_config=startup_config,
            )

            # Step 4: Execute tests
            logger.info("Step 4: Executing tests...")
            execution_result = await self._execute_tests(
                test_code=test_result.test_code,
                startup_config=startup_config,
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
                logger.info("Step 5: Cleaning up...")
                await self.project_runner.stop_project(project)

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
            framework="node-fetch",
        )

    async def _execute_tests(
        self,
        test_code: str,
        startup_config: StartupConfig,
    ) -> dict:
        """Execute test code and return results"""
        # Create temp file for test
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mjs", delete=False
        ) as f:
            f.write(test_code)
            test_file = f.name

        try:
            # Run with Node.js
            proc = await asyncio.create_subprocess_exec(
                "node",
                test_file,
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
            # Cleanup temp file
            try:
                os.unlink(test_file)
            except Exception:
                pass
