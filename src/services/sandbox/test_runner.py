"""Test generation and execution service"""

import logging
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from src.config import settings
from src.services.sandbox.docker_sandbox import DockerSandbox, ExecutionResult
from src.schema.response import FunctionalVerification, ExecutionResult as SchemaExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class TestGenerationResult:
    """Result of test generation"""

    test_code: str
    language: str
    framework: str


# System prompt for test generation
TEST_GENERATION_PROMPT = """You are an expert test engineer. Your task is to generate functional tests that verify the features described in the problem description are correctly implemented.

Given:
1. A problem description with required features
2. Analysis of where features are implemented
3. Project type and structure information

Generate test code that:
1. Tests each feature mentioned in the problem description
2. Uses appropriate testing framework for the project type
3. Makes actual API calls to verify functionality
4. Includes setup and teardown as needed

For Node.js projects:
- Use Jest or the project's existing test framework
- Use supertest for HTTP requests
- Include proper async/await handling

For Python projects:
- Use pytest
- Use requests or httpx for HTTP calls
- Include proper fixtures

Output ONLY the test code, no explanations. The code should be runnable as-is.
"""


class TestRunner:
    """
    Service for generating and running tests.

    Uses LLM to generate tests and Docker sandbox to execute them.
    """

    def __init__(self):
        self.sandbox = DockerSandbox()

    def is_available(self) -> bool:
        """Check if test runner is available (Docker required)"""
        return self.sandbox.is_available()

    async def generate_and_run_tests(
        self,
        problem_description: str,
        feature_analysis: list,
        project_dir: str,
        project_type: str,
    ) -> FunctionalVerification | None:
        """
        Generate tests and run them in sandbox.

        Args:
            problem_description: Original feature requirements
            feature_analysis: List of analyzed features
            project_dir: Path to project directory
            project_type: Type of project (nodejs, python, etc.)

        Returns:
            FunctionalVerification with test results, or None if unavailable
        """
        if not self.is_available():
            logger.warning("Test runner not available (Docker required)")
            return None

        try:
            # Generate test code
            test_result = await self._generate_tests(
                problem_description=problem_description,
                feature_analysis=feature_analysis,
                project_type=project_type,
            )

            logger.info(f"Generated {len(test_result.test_code)} chars of test code")

            # Run tests in sandbox
            execution_result = await self.sandbox.run_tests(
                project_dir=project_dir,
                test_code=test_result.test_code,
                project_type=project_type,
            )

            return FunctionalVerification(
                generated_test_code=test_result.test_code,
                execution_result=SchemaExecutionResult(
                    tests_passed=execution_result.success,
                    log=execution_result.stdout or execution_result.stderr,
                ),
            )

        except Exception as e:
            logger.exception(f"Test generation/execution failed: {e}")
            return None

    async def _generate_tests(
        self,
        problem_description: str,
        feature_analysis: list,
        project_type: str,
    ) -> TestGenerationResult:
        """Generate test code using LLM"""
        # Format feature analysis for prompt
        features_text = "\n".join(
            f"- {f.feature_description}: {', '.join(loc.file for loc in f.implementation_location)}"
            for f in feature_analysis
        )

        user_prompt = f"""## Problem Description
{problem_description}

## Feature Analysis
{features_text}

## Project Type
{project_type}

Generate functional test code to verify these features work correctly.
"""

        provider = AnthropicProvider(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
        )
        model = AnthropicModel(
            model_name=settings.anthropic_model_id,
            provider=provider,
        )

        agent = Agent(
            model=model,
            system_prompt=TEST_GENERATION_PROMPT,
        )

        result = await agent.run(user_prompt)
        test_code = result.output

        # Clean up code blocks if present
        if "```" in test_code:
            lines = test_code.split("\n")
            cleaned_lines = []
            in_code_block = False
            for line in lines:
                if line.startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block or not line.startswith("```"):
                    cleaned_lines.append(line)
            test_code = "\n".join(cleaned_lines)

        framework = self._detect_test_framework(project_type)

        return TestGenerationResult(
            test_code=test_code,
            language=project_type,
            framework=framework,
        )

    def _detect_test_framework(self, project_type: str) -> str:
        """Detect test framework based on project type"""
        frameworks = {
            "nodejs": "jest",
            "python": "pytest",
            "rust": "cargo-test",
            "go": "go-test",
        }
        return frameworks.get(project_type, "unknown")
