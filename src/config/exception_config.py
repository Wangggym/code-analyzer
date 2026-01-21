"""Exception handling configuration"""

import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AnalyzerException(Exception):
    """Base exception for code analyzer"""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ZipExtractionError(AnalyzerException):
    """Error during ZIP extraction"""

    def __init__(self, message: str):
        super().__init__(message, status_code=400)


class LLMAnalysisError(AnalyzerException):
    """Error during LLM analysis"""

    def __init__(self, message: str):
        super().__init__(message, status_code=500)


class SandboxExecutionError(AnalyzerException):
    """Error during sandbox execution"""

    def __init__(self, message: str):
        super().__init__(message, status_code=500)


def configure_exception_handlers(app: FastAPI) -> None:
    """Configure exception handlers for the FastAPI application"""

    @app.exception_handler(AnalyzerException)
    async def analyzer_exception_handler(
        request: Request, exc: AnalyzerException
    ) -> JSONResponse:
        logger.error(f"AnalyzerException: {exc.message}")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "type": type(exc).__name__},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "type": "InternalError"},
        )
