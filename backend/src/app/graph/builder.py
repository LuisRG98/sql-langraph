from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graph.edges import route_after_execute, route_after_generate, route_after_validate
from app.graph.nodes import GraphDeps, SqlAgentNodes
from app.graph.state import GraphState

# Alias a Any a propósito: los parámetros genéricos de CompiledStateGraph han cambiado
# entre versiones de LangGraph y no queremos acoplar nuestros tipos a ellos.
SqlAgent = Any


def recursion_limit(max_retries: int) -> int:
    """Pasos máximos permitidos. Cada reintento recorre 3 nodos (fix, validate, execute)."""
    return 10 + 3 * max_retries


def build_graph(deps: GraphDeps) -> SqlAgent:
    nodes = SqlAgentNodes(deps)
    graph = StateGraph(GraphState)

    graph.add_node("generate_sql", nodes.generate_sql)
    graph.add_node("validate_sql", nodes.validate_sql)
    graph.add_node("execute_sql", nodes.execute_sql)
    graph.add_node("fix_sql", nodes.fix_sql)
    graph.add_node("explain_result", nodes.explain_result)
    graph.add_node("reject_question", nodes.reject_question)
    graph.add_node("give_up", nodes.give_up)

    graph.add_edge(START, "generate_sql")
    graph.add_conditional_edges(
        "generate_sql",
        route_after_generate,
        {"validate_sql": "validate_sql", "reject_question": "reject_question"},
    )
    graph.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {"execute_sql": "execute_sql", "fix_sql": "fix_sql", "give_up": "give_up"},
    )
    graph.add_conditional_edges(
        "execute_sql",
        route_after_execute,
        {"explain_result": "explain_result", "fix_sql": "fix_sql", "give_up": "give_up"},
    )
    graph.add_edge("fix_sql", "validate_sql")
    graph.add_edge("explain_result", END)
    graph.add_edge("reject_question", END)
    graph.add_edge("give_up", END)

    return graph.compile()