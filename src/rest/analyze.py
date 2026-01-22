"""Code analysis endpoint"""

import logging
import os
import shutil
import tempfile
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, HTTPException

from src.config import settings
from src.schema.response import AnalyzeResponse
from src.services.zip_handler import extract_zip
from src.services.llm_analyzer import analyze_code
from src.services.report_generator import generate_report
from src.services.sandbox.test_runner import TestRunner

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Analysis"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_code_endpoint(
    problem_description: Annotated[str, Form(description="Feature requirements description")],
    code_zip: Annotated[UploadFile, File(description="ZIP file containing source code")],
    run_verification: Annotated[bool, Form(description="Run functional verification (bonus feature)")] = False,
) -> AnalyzeResponse:
    """
    Analyze code repository and generate feature location report.

    - **problem_description**: Natural language description of features to locate
    - **code_zip**: ZIP file containing the project source code
    - **run_verification**: If true, also run functional verification (starts project, generates and runs tests)

    Returns a structured JSON report with feature implementations and their locations.
    """
    # Validate file type
    if not code_zip.filename or not code_zip.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a ZIP archive")

    # Check file size
    content = await code_zip.read()
    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size: {settings.max_upload_size // 1024 // 1024}MB",
        )

    logger.info(f"Received analysis request: {len(problem_description)} chars description, {len(content)} bytes zip, verification={run_verification}")

    # For verification, we need a persistent directory (not auto-deleted)
    # because docker-compose needs the files to exist during container runtime
    if run_verification:
        temp_dir = tempfile.mkdtemp(prefix="code-analyzer-")
        try:
            return await _analyze_with_verification(
                problem_description=problem_description,
                content=content,
                temp_dir=temp_dir,
            )
        finally:
            # Cleanup temp dir
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir: {e}")
    else:
        # Simple analysis without verification
        with tempfile.TemporaryDirectory(prefix="code-analyzer-") as temp_dir:
            return await _analyze_simple(
                problem_description=problem_description,
                content=content,
                temp_dir=temp_dir,
            )


async def _analyze_simple(
    problem_description: str,
    content: bytes,
    temp_dir: str,
) -> AnalyzeResponse:
    """Simple analysis without functional verification"""
    # Save uploaded zip
    zip_path = os.path.join(temp_dir, "upload.zip")
    with open(zip_path, "wb") as f:
        f.write(content)

    # Extract zip
    extract_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    project_dir = await extract_zip(zip_path, extract_dir)

    logger.info(f"Extracted to: {project_dir}")

    # Analyze code with LLM
    analysis_result = await analyze_code(
        problem_description=problem_description,
        project_dir=project_dir,
    )

    # Generate report
    response = await generate_report(analysis_result)
    return response


async def _analyze_with_verification(
    problem_description: str,
    content: bytes,
    temp_dir: str,
) -> AnalyzeResponse:
    """Analysis with functional verification (bonus feature)"""
    # Save uploaded zip
    zip_path = os.path.join(temp_dir, "upload.zip")
    with open(zip_path, "wb") as f:
        f.write(content)

    # Extract zip
    extract_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    project_dir = await extract_zip(zip_path, extract_dir)

    logger.info(f"Extracted to: {project_dir}")

    # Step 1: Analyze code with LLM
    logger.info("=== Phase 1: Code Analysis ===")
    analysis_result = await analyze_code(
        problem_description=problem_description,
        project_dir=project_dir,
    )

    # Generate basic report
    response = await generate_report(analysis_result)

    # Step 2: Run functional verification
    logger.info("=== Phase 2: Functional Verification ===")
    try:
        test_runner = TestRunner()
        verification = await test_runner.run_functional_verification(
            problem_description=problem_description,
            feature_analysis=response.feature_analysis,
            project_dir=project_dir,
        )
        response.functional_verification = verification
        logger.info(f"Verification complete: tests_passed={verification.execution_result.tests_passed}")

    except Exception as e:
        logger.exception(f"Functional verification failed: {e}")
        # Don't fail the whole request, just report the error
        from src.schema.response import FunctionalVerification, ExecutionResult
        response.functional_verification = FunctionalVerification(
            generated_test_code=f"# Verification failed: {str(e)}",
            execution_result=ExecutionResult(
                tests_passed=False,
                log=f"Error: {str(e)}",
            ),
        )

    return response
