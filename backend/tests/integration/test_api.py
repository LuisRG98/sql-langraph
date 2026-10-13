from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from tests.helpers import RecordingTracer, ScriptedChatModel, build_test_agent

from app.api.deps import get_engine, get_schema, get_service
from app.api.rate_limit import RateLimiter
from app.core.config import Settings
from app.core.observability import Tracer, noop_trace
from app.db.hints import SCHEMA_HINTS
from app.db.schema import extract_schema
from app.main import create_app
from app.services.query_service import MAX_QUESTION_LENGTH, QueryService

ORIGIN = "http://localhost:5173"
SETTINGS = Settings(  # type: ignore[call-arg]
    _env_file=None, cors_origins=[ORIGIN], log_level="WARNING"
)
COUNT_SQL = "SELECT COUNT(*) AS total FROM customers"


@pytest.fixture
def make_client(ro_engine: Engine) -> Callable[..., TestClient]:
    def _make(
        responses: list[Any], *, limit: int = 100, tracer: Tracer = noop_trace
    ) -> TestClient:
        llm = ScriptedChatModel(responses=responses)
        service = QueryService(build_test_agent(ro_engine, llm), max_retries=3, tracer=tracer)
        schema = extract_schema(ro_engine, hints=SCHEMA_HINTS)

        app = create_app(SETTINGS, warm_up=False)
        app.state.rate_limiter = RateLimiter(limit, 60, time_fn=lambda: 0.0)
        app.dependency_overrides[get_service] = lambda: service
        app.dependency_overrides[get_engine] = lambda: ro_engine
        app.dependency_overrides[get_schema] = lambda: schema
        return TestClient(app)

    return _make


# ------------------------------------------------------------------ /api/query


def test_query_happy_path(make_client: Callable[..., TestClient]) -> None:
    client = make_client([COUNT_SQL, "Hay 50 clientes."])
    response = client.post("/api/query", json={"question": "¿Cuántos clientes hay?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["rows"] == [[50]]
    assert body["answer"] == "Hay 50 clientes."
    assert "LIMIT" in body["sql"]
    assert response.headers["x-request-id"]


def test_session_id_reaches_the_trace_and_user_id_does_not(
    make_client: Callable[..., TestClient],
) -> None:
    tracer = RecordingTracer()
    client = make_client([COUNT_SQL, "Hay 50."], tracer=tracer)
    client.post(
        "/api/query",
        json={"question": "¿Cuántos clientes hay?", "session_id": "demo-1", "user_id": "intruso"},
    )

    assert tracer.opened[0]["session_id"] == "demo-1"
    assert tracer.opened[0]["user_id"] is None


def test_business_failure_is_http_200_with_failed_status(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(["DROP TABLE x"] * 4)
    response = client.post("/api/query", json={"question": "borra todo"})

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": ""},
        {"question": "   "},
        {"question": "x" * (MAX_QUESTION_LENGTH + 1)},
        {"question": "ok", "session_id": "tiene espacios"},
        {"question": "ok", "session_id": "x" * 65},
    ],
)
def test_invalid_input_returns_422_without_calling_the_llm(
    make_client: Callable[..., TestClient], payload: dict[str, Any]
) -> None:
    client = make_client([])  # si el LLM se llamara, el test fallaría
    assert client.post("/api/query", json=payload).status_code == 422


def test_rate_limit_returns_429_with_retry_after(make_client: Callable[..., TestClient]) -> None:
    client = make_client(["CANNOT_ANSWER", "CANNOT_ANSWER"], limit=2)
    for _ in range(2):
        assert client.post("/api/query", json={"question": "hola"}).status_code == 200

    blocked = client.post("/api/query", json={"question": "hola"})
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"


def test_provider_quota_error_returns_429(make_client: Callable[..., TestClient]) -> None:
    client = make_client([RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")])
    response = client.post("/api/query", json={"question": "hola"})

    assert response.status_code == 429
    assert "proveedor" in response.json()["detail"]


def test_unexpected_error_returns_500_without_leaking_details(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client([RuntimeError("boom con detalles internos")])
    response = client.post("/api/query", json={"question": "hola"})

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "Referencia" in detail
    assert "boom" not in detail


# ------------------------------------------------------------------ meta


def test_schema_endpoint_lists_the_tables(make_client: Callable[..., TestClient]) -> None:
    response = make_client([]).get("/api/schema")

    assert response.status_code == 200
    names = {table["name"] for table in response.json()["tables"]}
    assert names == {"categories", "products", "customers", "orders", "order_items"}


def test_health_is_ok(make_client: Callable[..., TestClient]) -> None:
    response = make_client([]).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "langfuse": "disabled"}


def test_health_returns_503_when_the_database_is_down(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client([])
    broken = create_engine("sqlite:////directorio_que_no_existe_xyz/db.sqlite")
    client.app.dependency_overrides[get_engine] = lambda: broken  # type: ignore[attr-defined]

    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "error"
    assert response.json()["status"] == "degraded"


def test_openapi_documents_the_query_endpoint(make_client: Callable[..., TestClient]) -> None:
    paths = make_client([]).get("/openapi.json").json()["paths"]
    assert "/api/query" in paths
    assert "/api/schema" in paths


# ------------------------------------------------------------------ CORS


def test_cors_allows_the_configured_origin(make_client: Callable[..., TestClient]) -> None:
    response = make_client([]).options(
        "/api/query",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_cors_rejects_other_origins(make_client: Callable[..., TestClient]) -> None:
    response = make_client([]).options(
        "/api/query",
        headers={"Origin": "http://sitio-malicioso.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in response.headers