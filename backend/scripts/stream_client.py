"""Consume el endpoint SSE e imprime cada evento con su marca de tiempo.

Uso:
    python scripts/stream_client.py "¿Cuántos clientes hay por país?"
    python scripts/stream_client.py "Ingresos por categoría" --stop-after 1
"""
import argparse
import json
import sys
import time
from typing import Any

import httpx

URL = "http://127.0.0.1:8000/api/query/stream"


def show(started: float, event: str, data: dict[str, Any]) -> None:
    elapsed = time.perf_counter() - started
    if event == "step":
        mark = "[ok]" if data["ok"] else "[!!]"
        print(f"[{elapsed:5.1f}s] {mark} {data['label']}")
        if data["detail"]:
            print(f"          {data['detail']}")
    elif event == "result":
        print(f"[{elapsed:5.1f}s] RESULTADO ({data['status']}, {data['row_count']} filas)")
        print(f"          {data['answer']}")
    elif event == "error":
        print(f"[{elapsed:5.1f}s] ERROR {data['status']}: {data['detail']}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default="¿Cuántos clientes hay por país?")
    parser.add_argument("--stop-after", type=int, default=0, help="cortar tras N eventos")
    args = parser.parse_args()

    body = {"question": args.question, "session_id": "stream-cli"}
    started = time.perf_counter()
    received = 0

    with httpx.stream("POST", URL, json=body, timeout=60) as response:
        print(f"HTTP {response.status_code}  X-Request-ID={response.headers.get('x-request-id')}")
        if response.status_code != 200:
            response.read()
            print(response.text)
            return

        event = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                show(started, event, json.loads(line.removeprefix("data:").strip()))
                received += 1
                if args.stop_after and received >= args.stop_after:
                    print("(cliente cortó la conexión)")
                    return  # al salir del `with`, se cierra la conexión


if __name__ == "__main__":
    main()