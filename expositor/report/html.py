"""Static HTML report generation."""

from __future__ import annotations

from collections import Counter
from html import escape

from expositor.case_studies import run_mpeg4_case_study
from expositor.exporters.svg import graph_to_svg
from expositor.explain import build_top_down_explanation, render_top_down_explanation
from expositor.model import EdgeType, Graph, NodeType
from expositor.queries import QueryEngine


def _table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_html_report(graph: Graph, title: str = "Code Expositor Report") -> str:
    query = QueryEngine(graph)
    summary = query.repo_summary()
    repo = summary.get("repository") or {}
    modules = (repo.get("metadata") or {}).get("top_level_modules", [])
    node_counts = summary.get("node_counts", {})
    edge_counts = summary.get("edge_counts", {})

    files = sorted(
        graph.nodes_of_type(NodeType.SOURCE_FILE, NodeType.HEADER_FILE, NodeType.FILE),
        key=lambda item: item.path or item.label,
    )
    symbols = sorted(
        [
            node
            for node in graph.nodes.values()
            if node.type
            in {
                NodeType.FUNCTION.value,
                NodeType.METHOD.value,
                NodeType.STRUCT.value,
                NodeType.CLASS.value,
                NodeType.ENUM.value,
                NodeType.MACRO.value,
                NodeType.TYPEDEF.value,
            }
        ],
        key=lambda item: (item.path or "", item.metadata.get("line", 0), item.label),
    )
    includes = sorted(
        graph.edges_of_type(EdgeType.INCLUDES),
        key=lambda item: (graph.nodes[item.source].path or "", graph.nodes[item.target].path or ""),
    )
    calls = sorted(
        graph.edges_of_type(EdgeType.CALLS, EdgeType.MAY_CALL, EdgeType.UNRESOLVED),
        key=lambda item: (
            graph.nodes[item.source].label,
            graph.nodes[item.target].label,
            item.evidence[0].line if item.evidence else 0,
        ),
    )
    arch_edges = sorted(
        graph.edges_of_type(EdgeType.ARCH_SPECIFIC),
        key=lambda item: (graph.nodes[item.source].path or "", graph.nodes[item.target].label),
    )
    module_dependencies = sorted(
        [
            edge
            for edge in graph.edges_of_type(EdgeType.DEPENDS_ON)
            if graph.nodes[edge.source].type == NodeType.MODULE.value
            and graph.nodes[edge.target].type == NodeType.MODULE.value
        ],
        key=lambda item: (graph.nodes[item.source].label, graph.nodes[item.target].label),
    )
    translation_units = sorted(
        graph.nodes_of_type(NodeType.TRANSLATION_UNIT),
        key=lambda item: item.path or item.label,
    )

    explanation = render_top_down_explanation(build_top_down_explanation(graph))
    module_dependency_diagram = graph_to_svg(graph, "modules")
    include_dependency_diagram = graph_to_svg(graph, "includes")
    call_path_diagram = graph_to_svg(graph, "calls")
    architecture_diagram = graph_to_svg(graph, "architecture")

    node_rows = [[key, value] for key, value in sorted(node_counts.items())]
    edge_rows = [[key, value] for key, value in sorted(edge_counts.items())]
    module_rows = [[module] for module in modules]
    file_rows = [
        [node.path or "", node.type, node.metadata.get("language", ""), node.metadata.get("generated_candidate", False)]
        for node in files
    ]
    symbol_rows = [
        [
            node.label,
            node.type,
            node.path or "",
            node.metadata.get("line", ""),
            "definition" if node.metadata.get("definition") else "declaration",
        ]
        for node in symbols
    ]
    include_rows = [
        [
            graph.nodes[edge.source].path or graph.nodes[edge.source].label,
            graph.nodes[edge.target].path or graph.nodes[edge.target].label,
            edge.confidence,
            edge.extraction_tool,
        ]
        for edge in includes
    ]
    call_rows = [
        [
            graph.nodes[edge.source].label,
            graph.nodes[edge.target].label,
            edge.type,
            edge.confidence,
            edge.extraction_tool,
            edge.evidence[0].path if edge.evidence else "",
            edge.evidence[0].line if edge.evidence else "",
        ]
        for edge in calls
    ]
    arch_rows = [
        [
            graph.nodes[edge.source].path or "",
            graph.nodes[edge.target].label,
            edge.confidence,
            edge.metadata.get("reason", ""),
        ]
        for edge in arch_edges
    ]
    module_dependency_rows = [
        [
            graph.nodes[edge.source].label,
            graph.nodes[edge.target].label,
            edge.confidence,
            edge.metadata.get("source_file", ""),
            edge.metadata.get("target_file", ""),
        ]
        for edge in module_dependencies
    ]
    build_rows = [
        [
            node.path or node.label,
            ", ".join(node.metadata.get("include_paths", [])),
            ", ".join(node.metadata.get("macros", [])),
            node.metadata.get("target_arch", ""),
        ]
        for node in translation_units
    ]
    mpeg4_case_study = run_mpeg4_case_study(graph)
    mpeg4_candidate_rows = [
        [
            item["symbol"],
            item["type"],
            item.get("path") or "",
            item.get("line") or "",
            item["role"],
            ", ".join(item.get("match_basis") or []),
        ]
        for item in mpeg4_case_study["implementation_candidates"]
    ]
    mpeg4_file_rows = [
        [item["file"], ", ".join(item["evidence"])]
        for item in mpeg4_case_study["matching_files"]
    ]
    mpeg4_public_api_rows = [
        [
            item["label"],
            item["type"],
            item.get("path") or "",
            (item.get("metadata") or {}).get("line", ""),
        ]
        for item in mpeg4_case_study["public_api_candidates"]
    ]
    mpeg4_caller_rows = []
    for symbol, callers in sorted(mpeg4_case_study["direct_callers"].items()):
        for row in callers:
            edge = row["edge"]
            evidence = edge.get("evidence") or []
            first = evidence[0] if evidence else {}
            mpeg4_caller_rows.append(
                [
                    row["source"]["label"],
                    symbol,
                    edge["confidence"],
                    edge["extraction_tool"],
                    first.get("path") or "",
                    first.get("line") or "",
                ]
            )
    mpeg4_path_rows = []
    for symbol, paths in sorted(mpeg4_case_study["possible_paths"].items()):
        for path in paths:
            mpeg4_path_rows.append(
                [symbol, " -> ".join(node["label"] for node in path)]
            )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #17202a; background: #f7f9fb; }}
    header {{ background: #102a43; color: white; padding: 28px 36px; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    section {{ margin: 0 0 28px; background: white; border: 1px solid #d8e2ec; border-radius: 8px; padding: 20px; overflow: auto; }}
    h1, h2 {{ margin-top: 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e6edf3; padding: 7px 9px; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    pre {{ background: #102a43; color: #f0f4f8; padding: 16px; overflow: auto; border-radius: 6px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }}
    .diagram {{ margin: 18px 0 24px; }}
    .diagram svg {{ max-width: 100%; height: auto; border: 1px solid #e6edf3; }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <div>{escape(repo.get("label", "repository"))}</div>
  </header>
  <main>
    <section>
      <h2>Repository Overview</h2>
      <div class="grid">
        <div>{_table(["Node type", "Count"], node_rows)}</div>
        <div>{_table(["Edge type", "Count"], edge_rows)}</div>
      </div>
    </section>
    <section>
      <h2>Module Map</h2>
      {_table(["Top-level module"], module_rows)}
    </section>
    <section>
      <h2>Dependency Graph</h2>
      <div class="diagram">
        <h3>Module Dependency Diagram</h3>
        {module_dependency_diagram}
      </div>
      <div class="diagram">
        <h3>Include Dependency Graph</h3>
        {include_dependency_diagram}
      </div>
      <div class="diagram">
        <h3>Selected Call-path Diagram</h3>
        {call_path_diagram}
      </div>
      <div class="diagram">
        <h3>Architecture Slice Diagram</h3>
        {architecture_diagram}
      </div>
    </section>
    <section>
      <h2>Module Dependencies</h2>
      {_table(["Source module", "Target module", "Confidence", "Source file", "Target file"], module_dependency_rows)}
    </section>
    <section>
      <h2>Files</h2>
      {_table(["Path", "Type", "Language", "Generated candidate"], file_rows)}
    </section>
    <section>
      <h2>Symbol Browser</h2>
      {_table(["Name", "Type", "File", "Line", "Role"], symbol_rows)}
    </section>
    <section>
      <h2>Include Dependencies</h2>
      {_table(["Source", "Target", "Confidence", "Extraction tool"], include_rows)}
    </section>
    <section>
      <h2>Selected Call Paths</h2>
      {_table(["Caller", "Callee", "Edge", "Confidence", "Extraction tool", "File", "Line"], call_rows)}
    </section>
    <section>
      <h2>MPEG-4 Case Study</h2>
      <h3>Implementation Candidates</h3>
      {_table(["Symbol", "Type", "File", "Line", "Role", "Match basis"], mpeg4_candidate_rows)}
      <h3>Matching Files</h3>
      {_table(["File", "Evidence"], mpeg4_file_rows)}
      <h3>Public API Candidates</h3>
      {_table(["Symbol", "Type", "File", "Line"], mpeg4_public_api_rows)}
      <h3>Direct Callers</h3>
      {_table(["Caller", "Target", "Confidence", "Extraction tool", "File", "Line"], mpeg4_caller_rows)}
      <h3>Possible Static Paths</h3>
      {_table(["Target", "Path"], mpeg4_path_rows)}
    </section>
    <section>
      <h2>Architecture-specific Files</h2>
      {_table(["File", "Architecture", "Confidence", "Reason"], arch_rows)}
    </section>
    <section>
      <h2>Build Context</h2>
      {_table(["Translation unit", "Include paths", "Macros", "Target architecture"], build_rows)}
    </section>
    <section>
      <h2>Evidence-bound Summary</h2>
      <pre>{escape(explanation)}</pre>
    </section>
  </main>
</body>
</html>
"""


def report_metrics(graph: Graph) -> dict[str, dict[str, int]]:
    return {
        "node_counts": dict(Counter(node.type for node in graph.nodes.values())),
        "edge_counts": dict(Counter(edge.type for edge in graph.edges.values())),
    }
