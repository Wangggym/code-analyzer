"""Code analysis endpoint"""

import logging
import os
import tempfile
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, HTTPException

from src.config import settings
from src.schema.response import AnalyzeResponse
from src.services.zip_handler import extract_zip
from src.services.llm_analyzer import analyze_code
from src.services.report_generator import generate_report

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Analysis"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_code_endpoint(
    problem_description: Annotated[str, Form(description="Feature requirements description")],
    code_zip: Annotated[UploadFile, File(description="ZIP file containing source code")],
) -> AnalyzeResponse:
    """
    Analyze code repository and generate feature location report.

    - **problem_description**: Natural language description of features to locate
    - **code_zip**: ZIP file containing the project source code

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

    logger.info(f"Received analysis request: {len(problem_description)} chars description, {len(content)} bytes zip")

    # Create temp directory for extraction
    with tempfile.TemporaryDirectory(prefix="code-analyzer-") as temp_dir:
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
