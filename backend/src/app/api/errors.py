import logging

from app.services.query_service import InvalidQuestionError

logger = logging.getLogger(__name__)

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


def classify_error(exc: BaseException, request_id: str) -> tuple[int, str]:
    """Traduce una excepción a (código HTTP, mensaje seguro para el cliente).

    Es el único lugar donde se decide cómo se ve un error hacia afuera, y lo comparten
    el endpoint normal y el de streaming. Nunca devuelve detalles internos en el 500.
    """
    if isinstance(exc, InvalidQuestionError):
        return 422, str(exc)
    if is_rate_limit_error(exc):
        logger.warning("Límite del proveedor de IA (request_id=%s): %s", request_id, exc)
        return 429, "El proveedor de IA alcanzó su límite de uso. Espera un minuto."
    logger.error("Fallo inesperado (request_id=%s)", request_id, exc_info=exc)
    return 500, f"Error interno. Referencia: {request_id}"