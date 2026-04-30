from __future__ import annotations

from contextlib import asynccontextmanager

import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.core.database import close_db, init_db
from app.core.exceptions import AppError
from app.core.storage import ensure_dirs
from app.utils.logger import get_logger

logger = get_logger(__name__)

API_V1 = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting WACDeckStudio backend...")
    ensure_dirs()
    import app.core.database_models  # noqa: F401 — registers all models with Base.metadata
    await init_db()
    logger.info("Database initialized")

    from app.ai.gemini_client import init_gemini
    init_gemini()
    logger.info("Gemini initialized")

    yield

    # Shutdown
    await close_db()
    from app.core.cache import close_cache
    await close_cache()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="WACDeckStudio API",
        description="AI-powered presentation generation platform",
        version="1.0.0",
        lifespan=lifespan,
    )

    class ErrorLoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            try:
                return await call_next(request)
            except Exception as exc:
                logger.error(
                    f"Unhandled error on {request.method} {request.url.path}: {exc}\n"
                    + traceback.format_exc()
                )
                return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.add_middleware(ErrorLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            f"Unhandled error on {request.method} {request.url.path}: {exc}",
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "service": "WACDeckStudio"}

    @app.get("/", tags=["system"])
    async def root():
        return {"message": "WACDeckStudio API", "docs": "/docs"}

    # Include routers
    from app.api.v1.auth import router as auth_router
    from app.api.v1.templates import router as templates_router
    from app.api.v1.generation import router as generation_router
    from app.api.v1.presentations import router as presentations_router
    from app.api.v1.export import router as export_router
    from app.api.v1.import_pptx import router as import_router
    from app.api.v1.themes import router as themes_router
    from app.api.v1.share import router as share_router

    app.include_router(auth_router, prefix=API_V1)
    app.include_router(themes_router, prefix=API_V1)
    app.include_router(templates_router, prefix=API_V1)
    app.include_router(generation_router, prefix=API_V1)
    from app.api.v1.generate_sync import router as generate_sync_router
    app.include_router(generate_sync_router, prefix=API_V1)
    app.include_router(presentations_router, prefix=API_V1)
    app.include_router(export_router, prefix=API_V1)
    app.include_router(import_router, prefix=API_V1)
    app.include_router(share_router, prefix=API_V1)

    # Serve seed preview thumbnails as static files
    from pathlib import Path
    previews_dir = Path(__file__).resolve().parent.parent / "seeds" / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/previews", StaticFiles(directory=str(previews_dir)), name="previews")

    # Serve imported PPTX slide images as static files
    imports_dir = Path(__file__).resolve().parent.parent / "storage" / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/imports", StaticFiles(directory=str(imports_dir)), name="imports")

    return app


app = create_app()
