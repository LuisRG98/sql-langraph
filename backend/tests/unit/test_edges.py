from app.graph.edges import route_after_execute, route_after_generate, route_after_validate
from app.graph.state import GraphState


def test_unanswerable_goes_to_reject() -> None:
    assert route_after_generate({"status": "unanswerable"}) == "reject_question"


def test_normal_generation_goes_to_validation() -> None:
    assert route_after_generate({"status": "running"}) == "validate_sql"


def test_valid_sql_goes_to_execution() -> None:
    assert route_after_validate({"error": None}) == "execute_sql"


def test_invalid_sql_retries_while_budget_remains() -> None:
    state: GraphState = {"error": "bad", "retries": 1, "max_retries": 3}
    assert route_after_validate(state) == "fix_sql"


def test_invalid_sql_gives_up_when_budget_is_spent() -> None:
    state: GraphState = {"error": "bad", "retries": 3, "max_retries": 3}
    assert route_after_validate(state) == "give_up"


def test_successful_execution_goes_to_explanation() -> None:
    assert route_after_execute({"error": None}) == "explain_result"


def test_execution_error_retries_or_gives_up() -> None:
    assert route_after_execute({"error": "x", "retries": 0, "max_retries": 2}) == "fix_sql"
    assert route_after_execute({"error": "x", "retries": 2, "max_retries": 2}) == "give_up"


def test_zero_max_retries_never_retries() -> None:
    assert route_after_validate({"error": "x", "retries": 0, "max_retries": 0}) == "give_up"