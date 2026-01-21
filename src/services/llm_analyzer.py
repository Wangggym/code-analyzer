"""LLM-based code analysis service"""

import json
import logging
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from src.config import settings
from src.config.exception_config import LLMAnalysisError
from src.services.code_parser import parse_project, format_code_for_llm
from src.schema.response import FeatureAnalysis, ImplementationLocation

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Result of code analysis"""

    features: list[FeatureAnalysis]
    execution_suggestion: str
    raw_response: str


# System prompt for code analysis
ANALYSIS_SYSTEM_PROMPT = """You are an expert code analyst. Your task is to analyze source code and locate where specific features are implemented.

Given:
1. A problem description listing required features
2. Source code files from a project

You must:
1. Identify each feature mentioned in the problem description
2. Find the exact code locations (file, function, line numbers) that implement each feature
3. Provide a suggestion on how to run/execute the project

Output your analysis in the following JSON format:
{
  "feature_analysis": [
    {
      "feature_description": "Description of the feature",
      "implementation_location": [
        {
          "file": "path/to/file.ts",
          "function": "functionName",
          "lines": "startLine-endLine"
        }
      ]
    }
  ],
  "execution_plan_suggestion": "How to run the project (e.g., npm install && npm run start)"
}

Important:
- Be precise with line numbers - count from the actual file content
- Include ALL relevant implementation locations for each feature
- The function field should contain the actual function/method name
- If a feature spans multiple files, include all locations
- For the execution suggestion, analyze package.json/pyproject.toml for scripts
"""


def _create_primary_model() -> AnthropicModel:
    """Create the primary LLM model (Claude 4.5)"""
    provider = AnthropicProvider(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )
    return AnthropicModel(
        model_name=settings.anthropic_model_id,
        provider=provider,
    )


def _create_secondary_model() -> OpenAIModel:
    """Create the secondary LLM model (GPT-4o mini)"""
    provider = OpenAIProvider(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    return OpenAIModel(
        model_name=settings.openai_model_id,
        provider=provider,
    )


async def analyze_code(
    problem_description: str,
    project_dir: str,
    use_primary: bool = True,
) -> AnalysisResult:
    """
    Analyze code using LLM to locate feature implementations.

    Args:
        problem_description: Natural language description of features
        project_dir: Path to the extracted project directory
        use_primary: Whether to use primary model (Claude) or secondary (GPT-4o mini)

    Returns:
        AnalysisResult with feature locations and execution suggestion
    """
    try:
        # Parse project structure
        structure = await parse_project(project_dir)

        if not structure.files:
            raise LLMAnalysisError("No source code files found in the project")

        # Format code for LLM
        code_content = format_code_for_llm(structure)

        # Create user prompt
        user_prompt = f"""## Problem Description
{problem_description}

## Source Code
{code_content}

Please analyze the code and provide the feature location report in JSON format.
"""

        # Select model
        model = _create_primary_model() if use_primary else _create_secondary_model()
        model_name = settings.anthropic_model_id if use_primary else settings.openai_model_id

        logger.info(f"Analyzing with model: {model_name}")

        # Create agent and run analysis
        agent = Agent(
            model=model,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
        )

        result = await agent.run(user_prompt)
        raw_response = result.output

        logger.info(f"LLM response length: {len(raw_response)} chars")

        # Parse response
        analysis_result = _parse_llm_response(raw_response)

        return analysis_result

    except LLMAnalysisError:
        raise
    except Exception as e:
        logger.exception(f"LLM analysis failed: {e}")
        raise LLMAnalysisError(f"Analysis failed: {str(e)}")


def _parse_llm_response(response: str) -> AnalysisResult:
    """Parse LLM response into structured result"""
    try:
        # Extract JSON from response (handle markdown code blocks)
        json_str = response
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            json_str = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            json_str = response[start:end].strip()

        data = json.loads(json_str)

        features = []
        for feature_data in data.get("feature_analysis", []):
            locations = []
            for loc in feature_data.get("implementation_location", []):
                locations.append(
                    ImplementationLocation(
                        file=loc.get("file", ""),
                        function=loc.get("function", ""),
                        lines=loc.get("lines", ""),
                    )
                )
            features.append(
                FeatureAnalysis(
                    feature_description=feature_data.get("feature_description", ""),
                    implementation_location=locations,
                )
            )

        return AnalysisResult(
            features=features,
            execution_suggestion=data.get("execution_plan_suggestion", ""),
            raw_response=response,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        logger.debug(f"Raw response: {response}")
        raise LLMAnalysisError(f"Failed to parse analysis result: {e}")
