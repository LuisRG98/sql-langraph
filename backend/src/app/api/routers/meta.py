import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import Engine

from app.api.deps import get_engine, get_schema
from app.api.schemas import HealthResponse
from app.db.schema import DatabaseSchema

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])


@router.get("/api/schema", response_model=DatabaseSchema)
def database_schema(
    schema: Annotated[DatabaseSchema, Depends(get_schema)],
) -> DatabaseSchema:
    return schema


@router.get("/health", response_model=HealthResponse)
def health(
    request: Request,
    response: Response,
    engine: Annotated[Engine, Depends(get_engine)],
) -> HealthResponse:
    database: Literal["ok", "error"] = "ok"
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception:
        logger.exception("Health check: la base de datos no responde")
        database = "error"
        response.status_code = 503

    langfuse_on = request.app.state.settings.langfuse_enabled
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        database=database,
        langfuse="enabled" if langfuse_on else "disabled",
    )