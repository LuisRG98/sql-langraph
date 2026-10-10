"""Uso: python scripts/ask.py "¿Cuántos clientes hay por país?" """
import sys

from app.services.query_service import get_query_service


def main() -> None:
    if len(sys.argv) < 2:
        print('Uso: python scripts/ask.py "tu pregunta"')
        sys.exit(1)

    response = get_query_service().ask(" ".join(sys.argv[1:]))

    print(f"Estado:      {response.status}  (correcciones: {response.retries})")
    print(f"SQL:         {response.sql}")
    for i, attempt in enumerate(response.attempts, start=1):
        print(f"  fallo {i}:  {attempt.error}")
    print(f"Columnas:    {response.columns}")
    for row in response.rows[:10]:
        print(f"  {row}")
    print(f"\nRespuesta:   {response.answer}")


if __name__ == "__main__":
    main()