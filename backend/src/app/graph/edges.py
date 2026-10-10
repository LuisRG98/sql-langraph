from typing import Literal

from app.graph.state import GraphState


def route_after_generate(state: GraphState) -> Literal["validate_sql", "reject_question"]:
    if state.get("status") == "unanswerable":
        return "reject_question"
    return "validate_sql"


def _retry_or_give_up(state: GraphState) -> Literal["fix_sql", "give_up"]:
    if state.get("retries", 0) < state.get("max_retries", 0):
        return "fix_sql"
    return "give_up"


def route_after_validate(
    state: GraphState,
) -> Literal["execute_sql", "fix_sql", "give_up"]:
    if not state.get("error"):
        return "execute_sql"
    return _retry_or_give_up(state)


def route_after_execute(
    state: GraphState,
) -> Literal["explain_result", "fix_sql", "give_up"]:
    if not state.get("error"):
        return "explain_result"
    return _retry_or_give_up(state)