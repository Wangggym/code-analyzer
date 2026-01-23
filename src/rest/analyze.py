"""Code analysis endpoint"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
from typing import Annotated, AsyncGenerator, Callable

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse

from src.config import settings
from src.schema.response import AnalyzeResponse
from src.services.zip_handler import extract_zip
from src.services.llm_analyzer import analyze_code
from src.services.report_generator import generate_report
from src.services.sandbox.test_runner import TestRunner
from src.services.sse_helper import SSEEvent, format_sse, Stages

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Analysis"])

# Type for progress callback
ProgressCallback = Callable[[SSEEvent], None]


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

    NOTE: For run_verification=true, consider using /analyze/stream for real-time progress updates.
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
    # because Docker needs the files to exist during container runtime
    # Use settings.upload_dir as base for Docker volume compatibility
    if run_verification:
        os.makedirs(settings.upload_dir, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="session-", dir=settings.upload_dir)
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
        os.makedirs(settings.upload_dir, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="session-", dir=settings.upload_dir) as temp_dir:
            return await _analyze_simple(
                problem_description=problem_description,
                content=content,
                temp_dir=temp_dir,
            )


@router.post("/analyze/stream")
async def analyze_code_stream(
    problem_description: Annotated[str, Form(description="Feature requirements description")],
    code_zip: Annotated[UploadFile, File(description="ZIP file containing source code")],
) -> StreamingResponse:
    """
    Analyze code with functional verification using SSE streaming.

    Returns Server-Sent Events (SSE) with progress updates.

    Each event is JSON with format:
    ```
    data: {"stage": "analyzing_code", "message": "Analyzing project structure..."}
    data: {"stage": "complete", "message": "Done", "data": {...result...}}
    ```

    Stages: extracting, analyzing_code, analyzing_startup, starting_project,
            waiting_health, generating_tests, running_tests, cleanup, complete, error
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

    logger.info(f"Received streaming analysis request: {len(problem_description)} chars, {len(content)} bytes")

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events"""
        # Use settings.upload_dir as base for Docker volume compatibility
        os.makedirs(settings.upload_dir, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="session-", dir=settings.upload_dir)
        event_queue: asyncio.Queue[SSEEvent] = asyncio.Queue()

        def send_event(event: SSEEvent) -> None:
            """Callback to send progress event"""
            asyncio.get_event_loop().call_soon_threadsafe(
                event_queue.put_nowait, event
            )

        async def run_analysis() -> None:
            """Run the analysis in background"""
            try:
                result = await _analyze_with_verification_streaming(
                    problem_description=problem_description,
                    content=content,
                    temp_dir=temp_dir,
                    on_progress=send_event,
                )
                # Send final result
                send_event(SSEEvent(
                    stage=Stages.COMPLETE,
                    message="Analysis complete",
                    data=result.model_dump(),
                ))
            except Exception as e:
                logger.exception(f"Streaming analysis failed: {e}")
                send_event(SSEEvent(
                    stage=Stages.ERROR,
                    message=str(e),
                ))
            finally:
                # Cleanup
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass
                # Signal end
                send_event(SSEEvent(stage="__END__", message=""))

        # Start analysis task
        task = asyncio.create_task(run_analysis())

        try:
            while True:
                event = await event_queue.get()
                if event.stage == "__END__":
                    break
                yield format_sse(event)
        finally:
            task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
    """Analysis with functional verification (bonus feature) - non-streaming"""
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


async def _analyze_with_verification_streaming(
    problem_description: str,
    content: bytes,
    temp_dir: str,
    on_progress: ProgressCallback,
) -> AnalyzeResponse:
    """Analysis with functional verification - streaming version with progress callback"""

    # Step 0: Extract
    on_progress(SSEEvent(stage=Stages.EXTRACTING, message="Extracting code archive..."))

    zip_path = os.path.join(temp_dir, "upload.zip")
    with open(zip_path, "wb") as f:
        f.write(content)

    extract_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    project_dir = await extract_zip(zip_path, extract_dir)

    logger.info(f"Extracted to: {project_dir}")

    # Step 1: Analyze code with LLM
    on_progress(SSEEvent(stage=Stages.ANALYZING_CODE, message="Analyzing code structure with AI..."))

    analysis_result = await analyze_code(
        problem_description=problem_description,
        project_dir=project_dir,
    )

    # Generate basic report
    response = await generate_report(analysis_result)

    # Step 2: Run functional verification with progress
    try:
        test_runner = TestRunner()
        verification = await test_runner.run_functional_verification(
            problem_description=problem_description,
            feature_analysis=response.feature_analysis,
            project_dir=project_dir,
            on_progress=on_progress,
        )
        response.functional_verification = verification
        logger.info(f"Verification complete: tests_passed={verification.execution_result.tests_passed}")

    except Exception as e:
        logger.exception(f"Functional verification failed: {e}")
        on_progress(SSEEvent(stage=Stages.ERROR, message=f"Verification failed: {str(e)}"))
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
