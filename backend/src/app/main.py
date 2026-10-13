import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.rate_limit import RateLimiter
from app.api.routers import meta, query
from app.core.config import Settings, get_settings
from app.core.observability import flush_observability
from app.db.engine import get_readonly_engine

logger = logging.getLogger("app")


def create_app(settings: Settings | None = None, *, warm_up: bool = True) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if warm_up:
            get_readonly_engine()  # falla pronto, con mensaje claro, si falta la base
        yield
        if warm_up:
            flush_observability()  # no perder las últimas trazas al apagar

    app = FastAPI(
        title="Text-to-SQL API",
        version="0.1.0",
        description="Preguntas en lenguaje natural sobre una base de datos, con SQL validado.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute, 60)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "%s %s -> %d (%.0f ms) request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response

    # Se añade después del middleware anterior, así queda como capa más externa:
    # las peticiones "preflight" del navegador se resuelven antes de llegar a nada más.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    app.include_router(query.router)
    app.include_router(meta.router)
    return app