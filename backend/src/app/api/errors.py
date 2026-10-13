_RATE_LIMIT_MARKERS = ("429", "resourceexhausted", "resource_exhausted", "rate limit", "quota")


def is_rate_limit_error(exc: BaseException) -> bool:
    """Heurística: ¿el LLM falló por cuota o límite de uso?

    Cada proveedor lanza una clase de error distinta, y las clases cambian entre versiones.
    Para no acoplarnos a ninguna, buscamos pistas en el nombre y el mensaje de la excepción
    y de toda su cadena de causas.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = f"{type(current).__name__} {current}".lower()
        if any(marker in text for marker in _RATE_LIMIT_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False