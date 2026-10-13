from fastapi import HTTPException, Request
from sqlalchemy import Engine

from app.api.rate_limit import RateLimiter
from app.db.engine import get_readonly_engine
from app.db.schema import DatabaseSchema, get_database_schema
from app.services.query_service import QueryService, get_query_service

DB_UNAVAILABLE = "La base de datos no está disponible."


def get_service() -> QueryService:
    return get_query_service()


def get_engine() -> Engine:
    try:
        return get_readonly_engine()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE) from exc


def get_schema() -> DatabaseSchema:
    try:
        return get_database_schema()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE) from exc


def enforce_rate_limit(request: Request) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    client = request.client.host if request.client else "unknown"
    wait = limiter.check(client)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Demasiadas preguntas seguidas. Inténtalo de nuevo en {wait} segundos.",
            headers={"Retry-After": str(wait)},
        )