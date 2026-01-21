"""
Code Analyzer - FastAPI Application Entry
"""

import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.config.exception_config import configure_exception_handlers
from src.rest import health_router, analyze_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create FastAPI application"""

    app = FastAPI(
        title="Code Analyzer",
        description="AI-powered code analyzer that locates feature implementations",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Configure CORS
    if settings.debug:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Configure exception handlers
    configure_exception_handlers(app)

    # Register routers
    app.include_router(health_router)
    app.include_router(analyze_router)

    @app.on_event("startup")
    async def startup_event():
        logger.info(f"Starting {settings.app_name} on port {settings.api_port}")
        settings.print_config()

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.api_port,
        reload=settings.debug,
    )
