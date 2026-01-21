"""Report generation service"""

import logging

from src.services.llm_analyzer import AnalysisResult
from src.schema.response import AnalyzeResponse

logger = logging.getLogger(__name__)


async def generate_report(analysis_result: AnalysisResult) -> AnalyzeResponse:
    """
    Generate the final analysis report.

    Args:
        analysis_result: Result from LLM analysis

    Returns:
        AnalyzeResponse with structured report
    """
    response = AnalyzeResponse(
        feature_analysis=analysis_result.features,
        execution_plan_suggestion=analysis_result.execution_suggestion,
        functional_verification=None,  # Will be populated by sandbox execution
    )

    logger.info(f"Generated report with {len(response.feature_analysis)} features")

    return response
