"""Imprime el grafo en formato Mermaid (pégalo en https://mermaid.live)."""
from app.core.llm import get_llm
from app.db.engine import get_readonly_engine
from app.db.guardrail import get_sql_validator
from app.graph.builder import build_graph
from app.graph.nodes import GraphDeps


def main() -> None:
    deps = GraphDeps(
        llm=get_llm(),
        validator=get_sql_validator(),
        engine=get_readonly_engine(),
        schema_prompt="",
    )
    print(build_graph(deps).get_graph().draw_mermaid())


if __name__ == "__main__":
    main()