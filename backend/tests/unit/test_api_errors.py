import pytest

from app.api.errors import is_rate_limit_error

ResourceExhausted = type("ResourceExhausted", (Exception,), {})


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("429 Too Many Requests"),
        RuntimeError("Quota exceeded for metric"),
        RuntimeError("Rate limit reached"),
        ResourceExhausted("límite alcanzado"),
    ],
)
def test_detects_rate_limit_errors(exc: BaseException) -> None:
    assert is_rate_limit_error(exc)


@pytest.mark.parametrize("exc", [RuntimeError("boom"), ValueError("no such column: phone")])
def test_ignores_other_errors(exc: BaseException) -> None:
    assert not is_rate_limit_error(exc)


def test_detects_the_cause_inside_a_wrapper_exception() -> None:
    try:
        try:
            raise RuntimeError("429 quota exceeded")
        except RuntimeError as inner:
            raise ValueError("wrapper sin pistas") from inner
    except ValueError as outer:
        assert is_rate_limit_error(outer)


def test_self_referencing_exception_chain_terminates() -> None:
    exc = RuntimeError("boom")
    exc.__cause__ = exc
    assert not is_rate_limit_error(exc)