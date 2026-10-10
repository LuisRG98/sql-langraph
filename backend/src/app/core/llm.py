from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import get_settings


def get_llm(temperature: float | None = None) -> BaseChatModel:
    s = get_settings()
    return ChatGoogleGenerativeAI(
        model=s.llm_model,
        google_api_key=s.google_api_key.get_secret_value(),
        temperature=s.llm_temperature if temperature is None else temperature,
    )