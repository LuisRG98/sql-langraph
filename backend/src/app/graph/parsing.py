import re
from typing import Any

CANNOT_ANSWER = "CANNOT_ANSWER"

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def content_to_text(content: Any) -> str:
    """El contenido de un mensaje puede ser str o una lista de partes (según el proveedor)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return str(content)


def extract_sql(raw: str) -> str:
    """Quita las vallas de markdown y los espacios alrededor del SQL."""
    text = raw.strip()
    match = _FENCE.search(text)
    if match:
        text = match.group(1).strip()
    return text


def is_cannot_answer(text: str) -> bool:
    return text.strip().strip(".;`").upper() == CANNOT_ANSWER