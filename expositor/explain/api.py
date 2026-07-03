"""Evidence-bound explanation payloads and deterministic prose."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from expositor.model import EdgeType, Graph, Node, NodeType


SYMBOL_NODE_TYPES = {
    NodeType.FUNCTION.value,
    NodeType.METHOD.value,
    NodeType.MACRO.value,
    NodeType.STRUCT.value,
    NodeType.CLASS.value,
    NodeType.ENUM.value,
    NodeType.TYPEDEF.value,
    NodeType.PUBLIC_API.value,
    NodeType.SYMBOL.value,
}

FILE_LOCATION_NODE_TYPES = SYMBOL_NODE_TYPES | {
    NodeType.FILE.value,
    NodeType.SOURCE_FILE.value,
    NodeType.HEADER_FILE.value,
    NodeType.TRANSLATION_UNIT.value,
}


def _walk(value: Any) -> list[Any]:
    items = [value]
    if isinstance(value, dict):
        for nested in value.values():
            items.extend(_walk(nested))
    elif isinstance(value, list):
        for nested in value:
            items.extend(_walk(nested))
    return items


def _is_project_path(path: str | None) -> bool:
    return bool(path) and not str(path).startswith("<")


def _contract_locations(
    nodes: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    file_locations: dict[str, dict[str, Any]] = {}
    symbol_locations: dict[tuple[str, str, str], dict[str, Any]] = {}

    for node in nodes:
        path = node.get("path")
        if _is_project_path(path) and node.get("type") in FILE_LOCATION_NODE_TYPES:
            entry = file_locations.setdefault(
                str(path),
                {"path": str(path), "node_ids": [], "evidence_lines": []},
            )
            if node.get("id") not in entry["node_ids"]:
                entry["node_ids"].append(node.get("id"))

        if node.get("type") in SYMBOL_NODE_TYPES and _is_project_path(path):
            metadata = node.get("metadata") or {}
            line = metadata.get("line")
            key = (str(path), str(line or ""), str(node.get("id") or ""))
            symbol_locations[key] = {
                "node_id": node.get("id"),
                "name": node.get("label"),
                "type": node.get("type"),
                "path": path,
                "line": line,
                "role": "definition" if metadata.get("definition") else "declaration",
            }

    for item in evidence:
        path = item.get("path")
        if not _is_project_path(path):
            continue
        entry = file_locations.setdefault(
            str(path),
            {"path": str(path), "node_ids": [], "evidence_lines": []},
        )
        line = item.get("line")
        if line is not None and line not in entry["evidence_lines"]:
            entry["evidence_lines"].append(line)

    for entry in file_locations.values():
        entry["node_ids"].sort(key=lambda value: str(value))
        entry["evidence_lines"].sort()

    return (
        [file_locations[key] for key in sorted(file_locations)],
        sorted(
            symbol_locations.values(),
            key=lambda item: (
                str(item.get("path") or ""),
                item.get("line") or 0,
                str(item.get("name") or ""),
                str(item.get("node_id") or ""),
            ),
        ),
    )


def build_explanation_payload(
    *,
    question: str,
    graph_query: str,
    query_result: dict[str, Any],
    graph: Graph,
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    confidence: set[str] = set()

    for item in _walk(query_result):
        if not isinstance(item, dict):
            continue
        if {"id", "type", "label", "metadata"}.issubset(item):
            nodes[item["id"]] = item
        if {"id", "source", "target", "confidence", "extraction_tool"}.issubset(item):
            edges[item["id"]] = item
            confidence.add(item["confidence"])
            evidence.extend(item.get("evidence", []))

    for edge in edges.values():
        for node_id in (edge.get("source"), edge.get("target")):
            if node_id in graph.nodes:
                nodes[node_id] = graph.nodes[node_id].to_dict()

    selected_node_sequences = [
        item
        for item in _walk(query_result)
        if isinstance(item, list)
        and len(item) >= 2
        and all(isinstance(node, dict) and "id" in node for node in item)
    ]
    for sequence in selected_node_sequences:
        for source, target in zip(sequence, sequence[1:]):
            for edge in graph.edges.values():
                if edge.source == source["id"] and edge.target == target["id"]:
                    edges[edge.id] = edge.to_dict()
                    confidence.add(edge.confidence)
                    evidence.extend(item.to_dict() for item in edge.evidence)
                    nodes[edge.source] = graph.nodes[edge.source].to_dict()
                    nodes[edge.target] = graph.nodes[edge.target].to_dict()
                    break

    limitations: list[str] = [
        "This explanation is generated only from selected graph evidence.",
    ]
    if "UNRESOLVED" in confidence:
        limitations.append("Some relationships are unresolved and must not be treated as confirmed runtime behavior.")
    if any(edge.get("type") in {EdgeType.CALLS.value, EdgeType.MAY_CALL.value, EdgeType.UNRESOLVED.value} for edge in edges.values()):
        limitations.append("Static call edges are not runtime execution proof.")
    if not edges and not nodes:
        limitations.append("No graph evidence was selected by the query.")

    node_list = [nodes[key] for key in sorted(nodes)]
    edge_list = [edges[key] for key in sorted(edges)]
    file_locations, symbol_locations = _contract_locations(node_list, evidence)

    return {
        "question": question,
        "graph_query": graph_query,
        "nodes": node_list,
        "edges": edge_list,
        "evidence": evidence,
        "file_locations": file_locations,
        "symbol_locations": symbol_locations,
        "confidence": sorted(confidence),
        "limitations": limitations,
    }


def render_explanation(payload: dict[str, Any]) -> str:
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    evidence = payload.get("evidence", [])
    limitations = payload.get("limitations", [])
    confidence_counts = Counter(edge.get("confidence", "UNKNOWN") for edge in edges)

    lines = [
        "Answer",
        f"Selected graph evidence contains {len(nodes)} node(s) and {len(edges)} edge(s).",
        "",
        "Evidence",
    ]
    if evidence:
        for item in evidence[:12]:
            location = item.get("path", "")
            if item.get("line"):
                location = f"{location}:{item['line']}"
            snippet = item.get("snippet") or ""
            lines.append(f"- {location} {snippet}".rstrip())
    else:
        lines.append("- No evidence locations selected.")

    lines.extend(["", "Confidence"])
    if confidence_counts:
        for label, count in sorted(confidence_counts.items()):
            lines.append(f"- {label}: {count} edge(s)")
    else:
        lines.append("- No edge confidence labels selected.")

    lines.extend(["", "Uncertainty"])
    if limitations:
        lines.extend(f"- {item}" for item in limitations)
    else:
        lines.append("- No unresolved confidence labels in selected evidence.")

    relevant_files = sorted(
        {
            node.get("path")
            for node in nodes
            if node.get("path") and not str(node.get("path")).startswith("<")
        }
    )
    relevant_functions = sorted(
        {
            node.get("label")
            for node in nodes
            if node.get("type") in {"Function", "Method"}
        }
    )
    lines.extend(["", "Relevant files"])
    lines.extend(f"- {item}" for item in relevant_files[:20]) if relevant_files else lines.append("- None")
    lines.extend(["", "Relevant functions"])
    lines.extend(f"- {item}" for item in relevant_functions[:20]) if relevant_functions else lines.append("- None")
    lines.extend(["", "Suggested next query", f"- evidence_for({payload.get('graph_query')})"])
    return "\n".join(lines)


def build_repository_evidence_payload(
    graph: Graph,
    *,
    edge_limit: int = 96,
    node_limit: int = 160,
) -> dict[str, Any]:
    """Build the strict AI-contract payload for repository explanations."""

    edge_priority = {
        EdgeType.DEPENDS_ON.value: 0,
        EdgeType.INCLUDES.value: 1,
        EdgeType.CALLS.value: 2,
        EdgeType.MAY_CALL.value: 2,
        EdgeType.UNRESOLVED.value: 2,
        EdgeType.ARCH_SPECIFIC.value: 3,
        EdgeType.DEFINES.value: 4,
        EdgeType.DECLARES.value: 4,
        EdgeType.EXPORTED_BY.value: 5,
        EdgeType.COMPILED_IN.value: 6,
    }
    selected_edges = sorted(
        [
            edge
            for edge in graph.edges.values()
            if edge.type != EdgeType.CONTAINS.value
        ],
        key=lambda item: (
            edge_priority.get(item.type, 99),
            graph.nodes[item.source].path or graph.nodes[item.source].label,
            graph.nodes[item.target].path or graph.nodes[item.target].label,
            item.id,
        ),
    )[:edge_limit]

    node_ids = {
        node.id
        for node in graph.nodes.values()
        if node.type in {NodeType.REPOSITORY.value, NodeType.MODULE.value}
    }
    for edge in selected_edges:
        node_ids.add(edge.source)
        node_ids.add(edge.target)

    selected_nodes = sorted(
        [graph.nodes[node_id] for node_id in node_ids],
        key=lambda item: (
            item.type,
            item.path or "",
            item.metadata.get("line", 0),
            item.label,
            item.id,
        ),
    )[:node_limit]
    selected_node_ids = {node.id for node in selected_nodes}
    selected_edges = [
        edge
        for edge in selected_edges
        if edge.source in selected_node_ids and edge.target in selected_node_ids
    ]

    evidence = []
    for edge in selected_edges:
        for item in edge.evidence:
            payload = item.to_dict()
            payload.update(
                {
                    "edge": edge.id,
                    "edge_type": edge.type,
                    "confidence": edge.confidence,
                    "extraction_tool": edge.extraction_tool,
                }
            )
            evidence.append(payload)

    confidence = sorted({edge.confidence for edge in selected_edges})
    limitations = [
        "Payload contains selected graph evidence only; it is not a raw repository dump.",
        "Static call edges are not runtime execution proof.",
        "Possible and unresolved relationships must be labelled as uncertainty.",
    ]
    if any(edge.type == EdgeType.UNRESOLVED.value for edge in selected_edges):
        limitations.append("At least one selected relationship is unresolved.")

    node_list = [node.to_dict() for node in selected_nodes]
    edge_list = [edge.to_dict() for edge in selected_edges]
    file_locations, symbol_locations = _contract_locations(node_list, evidence)

    return {
        "question": "What is the top-down architecture of this repository?",
        "graph_query": "repository_evidence_payload",
        "nodes": node_list,
        "edges": edge_list,
        "evidence": evidence,
        "file_locations": file_locations,
        "symbol_locations": symbol_locations,
        "confidence": confidence,
        "limitations": limitations,
    }


def _node_path(node: Node) -> str:
    return node.path or node.label


def _file_nodes(graph: Graph) -> list[Node]:
    return sorted(
        graph.nodes_of_type(NodeType.SOURCE_FILE, NodeType.HEADER_FILE, NodeType.FILE),
        key=lambda item: _node_path(item),
    )


def _project_code_file_nodes(graph: Graph) -> list[Node]:
    return [
        node
        for node in _file_nodes(graph)
        if node.type in {NodeType.SOURCE_FILE.value, NodeType.HEADER_FILE.value}
        and not node.metadata.get("external")
        and not _node_path(node).startswith("<")
    ]


def _project_file_nodes(graph: Graph) -> list[Node]:
    return [
        node
        for node in _file_nodes(graph)
        if not node.metadata.get("external") and not _node_path(node).startswith("<")
    ]


def _symbol_nodes(graph: Graph) -> list[Node]:
    symbol_types = {
        NodeType.FUNCTION.value,
        NodeType.METHOD.value,
        NodeType.MACRO.value,
        NodeType.STRUCT.value,
        NodeType.CLASS.value,
        NodeType.ENUM.value,
        NodeType.TYPEDEF.value,
        NodeType.PUBLIC_API.value,
    }
    return sorted(
        [node for node in graph.nodes.values() if node.type in symbol_types],
        key=lambda item: (_node_path(item), item.metadata.get("line", 0), item.label),
    )


def _module_for_path(path: str | None) -> str:
    if not path:
        return "."
    parts = Path(path).parts
    return parts[0] if parts else "."


def _edge_location(edge: Any) -> str | None:
    if not edge.evidence:
        return None
    first = edge.evidence[0]
    if first.line:
        return f"{first.path}:{first.line}"
    return first.path


def build_top_down_explanation(graph: Graph) -> dict[str, Any]:
    """Build a deterministic top-down explanation from graph evidence."""

    repo_nodes = graph.nodes_of_type(NodeType.REPOSITORY)
    repo = repo_nodes[0] if repo_nodes else None
    files = _file_nodes(graph)
    project_files = _project_file_nodes(graph)
    project_code_files = _project_code_file_nodes(graph)
    symbols = _symbol_nodes(graph)
    include_edges = graph.edges_of_type(EdgeType.INCLUDES)
    dependency_edges = graph.edges_of_type(EdgeType.DEPENDS_ON)
    module_dependency_edges = [
        edge
        for edge in dependency_edges
        if graph.nodes[edge.source].type == NodeType.MODULE.value
        and graph.nodes[edge.target].type == NodeType.MODULE.value
    ]
    call_edges = graph.edges_of_type(EdgeType.CALLS, EdgeType.MAY_CALL, EdgeType.UNRESOLVED)
    arch_edges = graph.edges_of_type(EdgeType.ARCH_SPECIFIC)
    documentation_signals = []
    for node in files:
        for snippet in node.metadata.get("documentation_snippets", []):
            documentation_signals.append(
                {
                    "file": snippet["file"],
                    "line": snippet["line"],
                    "heading": snippet.get("heading"),
                    "text": snippet["text"],
                    "basis": "README/docs snippet; context signal only.",
                }
            )
    documentation_signals.sort(key=lambda item: (item["file"], item["line"], item.get("heading") or ""))

    files_by_module: dict[str, list[Node]] = defaultdict(list)
    symbols_by_module: dict[str, list[Node]] = defaultdict(list)
    includes_by_module: Counter[str] = Counter()
    dependents_by_module: Counter[str] = Counter()

    for file_node in project_code_files:
        files_by_module[_module_for_path(file_node.path)].append(file_node)
    for symbol in symbols:
        symbols_by_module[_module_for_path(symbol.path)].append(symbol)
    for edge in include_edges:
        source_module = _module_for_path(graph.nodes[edge.source].path)
        target_module = _module_for_path(graph.nodes[edge.target].path)
        includes_by_module[source_module] += 1
        if target_module != source_module:
            dependents_by_module[target_module] += 1

    module_responsibilities = []
    for module in sorted(files_by_module):
        module_files = files_by_module[module]
        module_symbols = symbols_by_module.get(module, [])
        type_counts = Counter(node.type for node in module_symbols)
        languages = Counter(node.metadata.get("language", "unknown") for node in module_files)
        representative_symbols = []
        seen_symbol_labels: set[str] = set()
        for node in sorted(
                module_symbols,
                key=lambda item: (
                    0 if item.type in {NodeType.PUBLIC_API.value, NodeType.FUNCTION.value, NodeType.METHOD.value} else 1,
                    item.path or "",
                    item.metadata.get("line", 0),
                    item.label,
                ),
        ):
            if node.label in seen_symbol_labels:
                continue
            representative_symbols.append(node.label)
            seen_symbol_labels.add(node.label)
            if len(representative_symbols) >= 8:
                break
        module_responsibilities.append(
            {
                "module": module,
                "file_count": len(module_files),
                "languages": dict(sorted(languages.items())),
                "symbol_counts": dict(sorted(type_counts.items())),
                "representative_symbols": representative_symbols,
                "outgoing_includes": includes_by_module[module],
                "incoming_cross_module_includes": dependents_by_module[module],
                "basis": "Inferred from canonical graph file inventory, symbols and include edges.",
            }
        )

    edge_degree: Counter[str] = Counter()
    symbol_count_by_file: Counter[str] = Counter()
    for edge in graph.edges.values():
        edge_degree[edge.source] += 1
        edge_degree[edge.target] += 1
    for symbol in symbols:
        if symbol.path:
            symbol_count_by_file[symbol.path] += 1

    important_files = []
    for node in sorted(
        project_code_files,
        key=lambda item: (
            -(edge_degree[item.id] + symbol_count_by_file[_node_path(item)]),
            _node_path(item),
        ),
    )[:12]:
        important_files.append(
            {
                "path": _node_path(node),
                "type": node.type,
                "language": node.metadata.get("language"),
                "symbol_count": symbol_count_by_file[_node_path(node)],
                "graph_degree": edge_degree[node.id],
                "evidence": "Ranked by graph degree and declared/defined symbols.",
            }
        )

    important_symbols = []
    for node in sorted(
        symbols,
        key=lambda item: (
            0 if item.type == NodeType.PUBLIC_API.value else 1,
            -(edge_degree[item.id]),
            item.path or "",
            item.metadata.get("line", 0),
            item.label,
        ),
    )[:16]:
        important_symbols.append(
            {
                "name": node.label,
                "type": node.type,
                "path": node.path,
                "line": node.metadata.get("line"),
                "role": "definition" if node.metadata.get("definition") else "declaration",
                "graph_degree": edge_degree[node.id],
            }
        )

    dependencies = []
    seen_dependency_summary: set[tuple[str, str, str]] = set()
    for edge in sorted(
        module_dependency_edges + include_edges,
        key=lambda item: (
            graph.nodes[item.source].path or graph.nodes[item.source].label,
            graph.nodes[item.target].path or graph.nodes[item.target].label,
            item.type,
        ),
    )[:24]:
        source_label = graph.nodes[edge.source].path or graph.nodes[edge.source].label
        target_label = graph.nodes[edge.target].path or graph.nodes[edge.target].label
        summary_key = (source_label, target_label, edge.type)
        if edge.type == EdgeType.DEPENDS_ON.value and summary_key in seen_dependency_summary:
            continue
        seen_dependency_summary.add(summary_key)
        dependencies.append(
            {
                "source": source_label,
                "target": target_label,
                "edge_type": edge.type,
                "confidence": edge.confidence,
                "evidence": _edge_location(edge),
            }
        )

    confidence_counts = Counter(edge.confidence for edge in graph.edges.values())
    unresolved_edges = [
        edge
        for edge in graph.edges.values()
        if edge.confidence in {"POSSIBLE", "UNRESOLVED"} or edge.type in {EdgeType.MAY_CALL.value, EdgeType.UNRESOLVED.value}
    ]
    uncertainty = [
        {
            "category": "confidence",
            "detail": f"{confidence} edge count: {count}",
        }
        for confidence, count in sorted(confidence_counts.items())
        if confidence != "CONFIRMED"
    ]
    if not call_edges:
        uncertainty.append(
            {
                "category": "call_graph",
                "detail": "No call edges are present in selected evidence.",
            }
        )
    if unresolved_edges:
        uncertainty.append(
            {
                "category": "static_analysis",
                "detail": "Possible or unresolved edges must not be treated as runtime execution proof.",
            }
        )

    evidence = []
    for edge in sorted(graph.edges.values(), key=lambda item: item.id):
        location = _edge_location(edge)
        if location:
            evidence.append(
                {
                    "edge": edge.id,
                    "edge_type": edge.type,
                    "confidence": edge.confidence,
                    "extraction_tool": edge.extraction_tool,
                    "location": location,
                    "source": graph.nodes[edge.source].label,
                    "target": graph.nodes[edge.target].label,
                }
            )
        if len(evidence) >= 32:
            break

    overview = {
        "repository": repo.label if repo else None,
        "file_count": len(project_files),
        "symbol_count": len(symbols),
            "module_count": len(files_by_module),
        "include_edge_count": len(include_edges),
        "call_edge_count": len(call_edges),
        "architecture_specific_file_count": len({edge.source for edge in arch_edges}),
        "node_counts": dict(sorted(Counter(node.type for node in graph.nodes.values()).items())),
        "edge_counts": dict(sorted(Counter(edge.type for edge in graph.edges.values()).items())),
    }

    return {
        "question": "What is the top-down architecture of this repository?",
        "graph_query": "top_down_explanation",
        "repository_overview": overview,
        "module_responsibilities": module_responsibilities,
        "important_files": important_files,
        "important_symbols": important_symbols,
        "dependency_summary": dependencies,
        "documentation_signals": documentation_signals[:16],
        "uncertainty": uncertainty,
        "evidence": evidence,
        "limitations": [
            "This explanation is generated only from extracted graph evidence.",
            "It does not infer runtime behavior from static analysis alone.",
            "Module responsibilities are deterministic summaries of file, symbol and dependency evidence.",
            "Documentation snippets provide context signals but do not create graph facts by themselves.",
        ],
    }


def render_top_down_explanation(explanation: dict[str, Any]) -> str:
    overview = explanation["repository_overview"]
    lines = [
        "Answer",
        (
            f"{overview.get('repository') or 'Repository'} contains "
            f"{overview['file_count']} file(s), {overview['symbol_count']} symbol(s), "
            f"{overview['module_count']} top-level module(s), "
            f"{overview['include_edge_count']} include edge(s) and "
            f"{overview['call_edge_count']} call edge(s) in the canonical graph."
        ),
        "",
        "Module responsibilities",
    ]
    for item in explanation["module_responsibilities"]:
        symbols = ", ".join(item["representative_symbols"][:5]) or "no extracted symbols"
        lines.append(
            f"- {item['module']}: {item['file_count']} file(s), "
            f"{item['outgoing_includes']} outgoing include(s), representative symbols: {symbols}"
        )

    lines.extend(["", "Important files"])
    if explanation["important_files"]:
        for item in explanation["important_files"][:10]:
            lines.append(
                f"- {item['path']} ({item['type']}, symbols={item['symbol_count']}, degree={item['graph_degree']})"
            )
    else:
        lines.append("- None")

    lines.extend(["", "Important symbols"])
    if explanation["important_symbols"]:
        for item in explanation["important_symbols"][:12]:
            location = item["path"] or ""
            if item.get("line"):
                location = f"{location}:{item['line']}"
            lines.append(f"- {item['name']} [{item['type']}] {location}".rstrip())
    else:
        lines.append("- None")

    lines.extend(["", "Dependency summary"])
    if explanation["dependency_summary"]:
        for item in explanation["dependency_summary"][:12]:
            location = f" ({item['evidence']})" if item.get("evidence") else ""
            lines.append(
                f"- {item['source']} -> {item['target']} "
                f"[{item['edge_type']} {item['confidence']}]{location}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "Documentation signals"])
    if explanation["documentation_signals"]:
        for item in explanation["documentation_signals"][:8]:
            heading = f" [{item['heading']}]" if item.get("heading") else ""
            lines.append(f"- {item['file']}:{item['line']}{heading}: {item['text']}")
    else:
        lines.append("- None")

    lines.extend(["", "Uncertainty"])
    if explanation["uncertainty"]:
        for item in explanation["uncertainty"]:
            lines.append(f"- {item['category']}: {item['detail']}")
    else:
        lines.append("- No non-confirmed graph edges in selected evidence.")

    lines.extend(["", "Evidence"])
    if explanation["evidence"]:
        for item in explanation["evidence"][:12]:
            lines.append(
                f"- {item['location']}: {item['source']} -> {item['target']} "
                f"[{item['edge_type']} {item['confidence']} via {item['extraction_tool']}]"
            )
    else:
        lines.append("- No evidence locations selected.")

    lines.extend(["", "Suggested next query", "- symbols_in(<module-or-file>)"])
    return "\n".join(lines)
