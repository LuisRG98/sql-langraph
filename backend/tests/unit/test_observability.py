import pytest

from app.core import observability
from app.core.config import Settings
from app.core.observability import ScoreSpec, TraceHandle, noop_trace, trace_query


@pytest.fixture
def no_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simula una configuración sin claves de Langfuse, sin leer el .env real."""
    settings = Settings(_env_file=None, langfuse_public_key="", langfuse_secret_key="")  # type: ignore[call-arg]
    monkeypatch.setattr(observability, "get_settings", lambda: settings)
    observability.get_langfuse.cache_clear()
    yield
    observability.get_langfuse.cache_clear()


def test_langfuse_is_disabled_without_keys(no_langfuse: None) -> None:
    assert observability.get_langfuse() is None


def test_trace_query_without_keys_yields_an_empty_handle(no_langfuse: None) -> None:
    with trace_query("x", session_id="s", user_id=None, tags=["a"], metadata=None) as handle:
        assert handle.callbacks == []
        assert handle.trace_id is None


def test_record_without_keys_does_nothing(no_langfuse: None) -> None:
    with trace_query("x") as handle:
        handle.record(inputs={"q": 1}, outputs={"a": 2}, scores=[ScoreSpec("answered", 1.0)])


def test_flush_without_keys_does_not_fail(no_langfuse: None) -> None:
    observability.flush_observability()


def test_noop_trace_yields_an_empty_handle() -> None:
    with noop_trace("x") as handle:
        assert isinstance(handle, TraceHandle)
        assert handle.callbacks == []
        handle.record(inputs=None, outputs=None, scores=[])


def test_score_spec_defaults_to_numeric() -> None:
    score = ScoreSpec("retries", 2.0)
    assert score.data_type == "NUMERIC"
    assert score.comment is None