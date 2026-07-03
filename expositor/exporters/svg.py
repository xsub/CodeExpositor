"""Dependency-free SVG export for quick graph validation."""

from __future__ import annotations

from math import ceil, sqrt

from expositor.exporters.dot import filtered_edges
from expositor.model import Graph


def _xml(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def graph_to_svg(
    graph: Graph,
    graph_filter: str = "all",
    *,
    renderer: str = "internal",
) -> str:
    if renderer in {"graphviz", "auto"}:
        from expositor.exporters.graphviz import graph_to_graphviz_svg

        try:
            return graph_to_graphviz_svg(graph, graph_filter)
        except RuntimeError:
            if renderer == "graphviz":
                raise

    edges = filtered_edges(graph, graph_filter)
    node_ids = sorted({edge.source for edge in edges} | {edge.target for edge in edges})
    if not node_ids:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="160" '
            'viewBox="0 0 640 160"><text x="24" y="80" '
            'font-family="monospace" font-size="16">Empty graph</text></svg>\n'
        )

    columns = max(1, ceil(sqrt(len(node_ids))))
    cell_w = 220
    cell_h = 120
    margin = 48
    width = columns * cell_w + margin * 2
    rows = ceil(len(node_ids) / columns)
    height = rows * cell_h + margin * 2
    positions: dict[str, tuple[int, int]] = {}
    for index, node_id in enumerate(node_ids):
        row = index // columns
        column = index % columns
        positions[node_id] = (margin + column * cell_w + 80, margin + row * cell_h + 40)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#555"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]

    for edge in edges:
        x1, y1 = positions[edge.source]
        x2, y2 = positions[edge.target]
        lines.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            'stroke="#777" stroke-width="1.4" marker-end="url(#arrow)"/>'
        )
        mid_x = (x1 + x2) // 2
        mid_y = (y1 + y2) // 2
        lines.append(
            f'<text x="{mid_x}" y="{mid_y - 4}" text-anchor="middle" '
            'font-family="monospace" font-size="9" fill="#555">'
            f'{_xml(edge.type)}</text>'
        )

    for node_id in node_ids:
        node = graph.nodes[node_id]
        x, y = positions[node_id]
        lines.append(f'<rect x="{x - 72}" y="{y - 24}" width="144" height="48" rx="6" fill="#eef5ff" stroke="#2b5c88"/>')
        lines.append(
            f'<text x="{x}" y="{y - 4}" text-anchor="middle" '
            'font-family="monospace" font-size="10" font-weight="600">'
            f'{_xml(node.label[:24])}</text>'
        )
        lines.append(
            f'<text x="{x}" y="{y + 12}" text-anchor="middle" '
            'font-family="monospace" font-size="9" fill="#555">'
            f'{_xml(node.type)}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines) + "\n"
