"""Verifica que el entorno, el LLM y Langfuse estén bien configurados."""
import sys

from langchain_google_genai import ChatGoogleGenerativeAI
from langfuse import Langfuse

from app.core.config import get_settings

 
def check_llm() -> bool:
    s = get_settings()
    if not s.google_api_key.get_secret_value():
        print("❌ LLM: falta GOOGLE_API_KEY")
        return False
    try:
        llm = ChatGoogleGenerativeAI(
            model=s.llm_model,
            google_api_key=s.google_api_key.get_secret_value(),
            temperature=s.llm_temperature,
        )
        reply = llm.invoke("Responde solo con la palabra: ok")
        print(f"✅ LLM ({s.llm_model}): {reply.content!r}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"❌ LLM: {exc}")
        return False


def check_langfuse() -> bool:
    s = get_settings()
    if not s.langfuse_enabled:
        print("❌ Langfuse: faltan claves")
        return False
    client = Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key.get_secret_value(),
        host=s.langfuse_host,
    )
    ok = client.auth_check()
    print("✅ Langfuse: autenticado" if ok else "❌ Langfuse: credenciales inválidas")
    return bool(ok)


if __name__ == "__main__":
    results = [check_llm(), check_langfuse()]
    sys.exit(0 if all(results) else 1)