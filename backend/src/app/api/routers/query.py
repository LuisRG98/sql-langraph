import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import enforce_rate_limit, get_service
from app.api.errors import is_rate_limit_error
from app.api.schemas import ErrorResponse, QueryRequest
from app.services.query_service import InvalidQuestionError, QueryResponse, QueryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["query"])


@router.post(
    "/query",
    response_model=QueryResponse,
    dependencies=[Depends(enforce_rate_limit)],
    responses={
        422: {"model": ErrorResponse, "description": "Pregunta inválida"},
        429: {"model": ErrorResponse, "description": "Demasiadas peticiones o cuota del LLM"},
        500: {"model": ErrorResponse, "description": "Error interno"},
    },
)
def ask(
    payload: QueryRequest,
    request: Request,
    service: Annotated[QueryService, Depends(get_service)],
) -> QueryResponse:
    request_id = getattr(request.state, "request_id", "n/a")
    try:
        return service.ask(payload.question, session_id=payload.session_id)
    except InvalidQuestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if is_rate_limit_error(exc):
            logger.warning("Límite del proveedor de IA (request_id=%s): %s", request_id, exc)
            raise HTTPException(
                status_code=429,
                detail="El proveedor de IA alcanzó su límite de uso. Espera un minuto.",
            ) from exc
        logger.exception("Fallo inesperado (request_id=%s)", request_id)
        raise HTTPException(
            status_code=500,
            detail=f"Error interno. Referencia: {request_id}",
        ) from exc