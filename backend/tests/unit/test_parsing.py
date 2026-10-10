import pytest

from app.graph.parsing import content_to_text, extract_sql, is_cannot_answer


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SELECT 1", "SELECT 1"),
        ("  SELECT 1  \n", "SELECT 1"),
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        ("```SQL\nSELECT 1\n```", "SELECT 1"),
        ("```\nSELECT 1\n```", "SELECT 1"),
        ("Here is the query:\n```sql\nSELECT 1;\n```\nHope it helps", "SELECT 1;"),
    ],
)
def test_extract_sql(raw: str, expected: str) -> None:
    assert extract_sql(raw) == expected


@pytest.mark.parametrize("text", ["CANNOT_ANSWER", " cannot_answer ", "CANNOT_ANSWER.", "`CANNOT_ANSWER`"])
def test_detects_cannot_answer(text: str) -> None:
    assert is_cannot_answer(text)


@pytest.mark.parametrize("text", ["SELECT 1", "", "I CANNOT_ANSWER this"])
def test_does_not_flag_normal_text(text: str) -> None:
    assert not is_cannot_answer(text)


def test_content_to_text_handles_plain_string() -> None:
    assert content_to_text("hola") == "hola"


def test_content_to_text_joins_text_parts() -> None:
    parts = [{"type": "text", "text": "SELECT "}, {"type": "text", "text": "1"}, "!"]
    assert content_to_text(parts) == "SELECT 1!"


def test_content_to_text_ignores_non_text_parts() -> None:
    assert content_to_text([{"type": "image", "url": "x"}, {"type": "text", "text": "ok"}]) == "ok"