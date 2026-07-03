"""Graphviz DOT export from the canonical graph."""

from __future__ import annotations

from expositor.model import Edge, EdgeType, Graph, NodeType


GRAPH_FILTERS = {
    "includes": {EdgeType.INCLUDES.value, EdgeType.DEPENDS_ON.value},
    "calls": {EdgeType.CALLS.value, EdgeType.MAY_CALL.value, EdgeType.UNRESOLVED.value},
    "architecture": {EdgeType.ARCH_SPECIFIC.value},
    "all": None,
}


def _quote(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def filtered_edges(graph: Graph, graph_filter: str = "all") -> list[Edge]:
    if graph_filter == "modules":
        module_edges = [
            edge
            for edge in graph.edges.values()
            if edge.type == EdgeType.DEPENDS_ON.value
            and graph.nodes[edge.source].type == NodeType.MODULE.value
            and graph.nodes[edge.target].type == NodeType.MODULE.value
        ]
        deduped: dict[tuple[str, str, str], Edge] = {}
        for edge in sorted(module_edges, key=lambda item: (item.source, item.target, item.id)):
            deduped.setdefault((edge.source, edge.target, edge.type), edge)
        return list(deduped.values())

    allowed = GRAPH_FILTERS.get(graph_filter)
    edges = list(graph.edges.values())
    if allowed is not None:
        edges = [edge for edge in edges if edge.type in allowed]
    return sorted(edges, key=lambda item: (item.type, item.source, item.target, item.id))


def graph_to_dot(graph: Graph, graph_filter: str = "all") -> str:
    edges = filtered_edges(graph, graph_filter)
    node_ids = {edge.source for edge in edges} | {edge.target for edge in edges}
    nodes = [graph.nodes[node_id] for node_id in sorted(node_ids)]

    lines = ["digraph CodeExpositor {", "  rankdir=LR;", "  node [shape=box, fontsize=10];"]
    for node in nodes:
        label = f"{node.label}\\n{node.type}"
        if node.path and node.path != node.label:
            label = f"{node.label}\\n{node.path}"
        lines.append(f'  "{_quote(node.id)}" [label="{_quote(label)}"];')
    for edge in edges:
        label = f"{edge.type}\\n{edge.confidence}"
        lines.append(
            f'  "{_quote(edge.source)}" -> "{_quote(edge.target)}" '
            f'[label="{_quote(label)}"];'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"
