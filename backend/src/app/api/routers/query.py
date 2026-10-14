from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.deps import enforce_rate_limit, get_service
from app.api.errors import classify_error
from app.api.schemas import ErrorResponse, QueryRequest
from app.api.streaming import sse_stream
from app.services.query_service import QueryResponse, QueryService

router = APIRouter(prefix="/api", tags=["query"])

ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    422: {"model": ErrorResponse, "description": "Pregunta inválida"},
    429: {"model": ErrorResponse, "description": "Demasiadas peticiones o cuota del LLM"},
    500: {"model": ErrorResponse, "description": "Error interno"},
}


@router.post(
    "/query",
    response_model=QueryResponse,
    dependencies=[Depends(enforce_rate_limit)],
    responses=ERROR_RESPONSES,
)
def ask(
    payload: QueryRequest,
    request: Request,
    service: Annotated[QueryService, Depends(get_service)],
) -> QueryResponse:
    request_id = getattr(request.state, "request_id", "n/a")
    try:
        return service.ask(payload.question, session_id=payload.session_id)
    except Exception as exc:
        status, detail = classify_error(exc, request_id)
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post(
    "/query/stream",
    dependencies=[Depends(enforce_rate_limit)],
    response_class=StreamingResponse,
    responses={
        **ERROR_RESPONSES,
        200: {
            "description": "Flujo SSE con eventos `step`, `result` y `error`.",
            "content": {"text/event-stream": {}},
        },
    },
)
def ask_stream(
    payload: QueryRequest,
    request: Request,
    service: Annotated[QueryService, Depends(get_service)],
) -> StreamingResponse:
    request_id = getattr(request.state, "request_id", "n/a")

    # Se valida ANTES de transmitir: después del 200 ya no se puede devolver un 422.
    try:
        question = service.validate_question(payload.question)
    except Exception as exc:
        status, detail = classify_error(exc, request_id)
        raise HTTPException(status_code=status, detail=detail) from exc

    return StreamingResponse(
        sse_stream(
            lambda cancel: service.stream(
                question, session_id=payload.session_id, cancel=cancel
            ),
            request_id=request_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )