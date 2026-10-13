from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.query_service import MAX_QUESTION_LENGTH


class QueryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    langfuse: Literal["enabled", "disabled"]


class ErrorResponse(BaseModel):
    detail: str