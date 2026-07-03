"""Command line interface for Code Expositor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from expositor.architecture import classify_architecture
from expositor.build_context import (
    capture_make_build_context,
    load_build_context,
    write_compile_commands,
)
from expositor.case_studies import run_mpeg4_case_study
from expositor.doctor import run_doctor
from expositor.explain import (
    build_explanation_payload,
    build_repository_evidence_payload,
    build_top_down_explanation,
    render_explanation,
    render_top_down_explanation,
)
from expositor.exporters import graph_to_dot, graph_to_svg
from expositor.graph import build_canonical_graph, build_indexes
from expositor.includes import build_include_graph
from expositor.intake import scan_repository
from expositor.outline import build_outline
from expositor.queries import QueryEngine
from expositor.report import render_html_report
from expositor.semantic import build_clang_semantic_index
from expositor.storage import load_graph, save_graph, storage_info
from expositor.symbols import build_symbol_index
from expositor.model import Graph, graph_schema
from expositor.validation import validate_graph


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _write(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _load_or_build_graph(
    repo: str,
    db: str | None = None,
    *,
    semantic: bool = False,
    semantic_limit: int | None = None,
    outline_source: str = "regex",
    symbol_source: str = "outline",
):
    if db and Path(db).exists():
        return load_graph(db)
    graph = build_canonical_graph(
        repo,
        semantic=semantic,
        semantic_limit=semantic_limit,
        outline_source=outline_source,
        symbol_source=symbol_source,
    )
    if db:
        save_graph(db, graph)
    return graph


def cmd_schema(args: argparse.Namespace) -> int:
    _write(_json(graph_schema()), args.output)
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    _write(_json(scan_repository(args.repo).to_dict()), args.output)
    return 0


def cmd_outline(args: argparse.Namespace) -> int:
    _write(_json(build_outline(args.repo, source=args.source).to_dict()), args.output)
    return 0


def cmd_symbols(args: argparse.Namespace) -> int:
    outline = None if args.source == "ctags" else build_outline(args.repo, source=args.outline_source)
    _write(
        _json(build_symbol_index(args.repo, outline, source=args.source).to_dict()),
        args.output,
    )
    return 0


def cmd_includes(args: argparse.Namespace) -> int:
    _write(_json(build_include_graph(args.repo).to_dict()), args.output)
    return 0


def cmd_build_context(args: argparse.Namespace) -> int:
    if args.make_target:
        context = capture_make_build_context(args.repo, args.make_target)
        if args.write_compile_commands:
            output_path = write_compile_commands(
                args.repo,
                context,
                args.write_compile_commands,
            )
            try:
                context.compile_commands_path = output_path.resolve().relative_to(Path(args.repo).resolve()).as_posix()
            except ValueError:
                context.compile_commands_path = output_path.resolve().as_posix()
    else:
        context = load_build_context(args.repo)
    _write(_json(context.to_dict()), args.output)
    return 0


def cmd_architecture(args: argparse.Namespace) -> int:
    _write(_json(classify_architecture(args.repo).to_dict()), args.output)
    return 0


def cmd_semantic(args: argparse.Namespace) -> int:
    _write(
        _json(build_clang_semantic_index(args.repo, limit=args.limit).to_dict()),
        args.output,
    )
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    graph = build_canonical_graph(
        args.repo,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    if args.db:
        save_graph(args.db, graph)
    _write(_json(graph.to_dict()), args.output)
    return 0


def _text_validation_report(report: dict[str, Any]) -> str:
    lines = [
        "Graph validation",
        f"- ok: {report['ok']}",
        f"- nodes: {report['graph_counts']['nodes']}",
        f"- edges: {report['graph_counts']['edges']}",
        f"- errors: {report['issue_counts']['error']}",
        f"- warnings: {report['issue_counts']['warning']}",
    ]
    if report["issues"]:
        lines.append("")
        lines.append("Issues")
        for issue in report["issues"]:
            lines.append(
                f"- [{issue['severity']}] {issue['code']} "
                f"{issue['subject']}: {issue['message']}"
            )
    return "\n".join(lines) + "\n"


def cmd_validate(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    report = validate_graph(graph).to_dict()
    if args.format == "json":
        _write(_json(report), args.output)
    else:
        _write(_text_validation_report(report), args.output)
    return 0 if report["ok"] else 1


def _text_doctor(report: dict[str, Any]) -> str:
    lines = [
        "Code Expositor doctor",
        f"- ok: {report['ok']}",
    ]
    for status, count in report.get("counts", {}).items():
        lines.append(f"- {status}: {count}")
    lines.append("")
    lines.append("Checks")
    for check in report["checks"]:
        lines.append(f"- [{check['status']}] {check['name']}: {check['message']}")
        lines.extend(_doctor_detail_lines(check))
    return "\n".join(lines) + "\n"


def _doctor_detail_lines(check: dict[str, Any]) -> list[str]:
    metadata = check.get("metadata") or {}
    name = check.get("name")
    if name == "tiny_mpeg4_case_study":
        lines = [f"  - path count: {metadata.get('path_count', 0)}"]
        for candidate in (metadata.get("implementation_candidates") or [])[:3]:
            symbol = candidate.get("symbol", "<unknown>")
            role = candidate.get("role", "unknown")
            path = candidate.get("path", "<unknown>")
            line = candidate.get("line")
            location = f"{path}:{line}" if line else path
            lines.append(f"  - implementation: {symbol} [{role}] {location}")
        return lines
    if name == "tiny_exports_report":
        lines = [
            "  - diagrams: "
            f"svg={metadata.get('svg_count', 0)}, "
            f"html_svg={metadata.get('html_svg_count', 0)}"
        ]
        missing_sections = metadata.get("missing_sections") or []
        if missing_sections:
            lines.append(f"  - missing sections: {', '.join(missing_sections)}")
        return lines
    if name == "tiny_storage_store":
        return [
            "  - storage: "
            f"nodes={metadata.get('nodes', 0)}, "
            f"edges={metadata.get('edges', 0)}, "
            f"adjacency_out={metadata.get('adjacency_out', 0)}, "
            f"adjacency_in={metadata.get('adjacency_in', 0)}"
        ]
    if name == "ffmpeg_mpeg4_readiness":
        lines = [
            f"  - path: {metadata.get('path', '<unknown>')}",
            f"  - MPEG-4 candidates: {metadata.get('mpeg4_candidate_count', 0)}",
        ]
        for candidate in (metadata.get("mpeg4_candidates") or [])[:5]:
            lines.append(f"  - candidate: {candidate}")
        missing_modules = metadata.get("missing_modules") or []
        if missing_modules:
            lines.append(f"  - missing modules: {', '.join(missing_modules)}")
        return lines
    if name == "ffmpeg_build_context":
        lines = [
            f"  - compile commands: {metadata.get('compile_commands_path') or '<missing>'}",
            f"  - translation units: {metadata.get('translation_unit_count', 0)}",
            f"  - libavcodec translation units: {metadata.get('libavcodec_translation_unit_count', 0)}",
            f"  - MPEG-4 translation units: {metadata.get('mpeg4_translation_unit_count', 0)}",
        ]
        for unit in (metadata.get("mpeg4_translation_units") or [])[:5]:
            lines.append(f"  - MPEG-4 TU: {unit}")
        for unit in (metadata.get("sample_translation_units") or [])[:3]:
            lines.append(f"  - sample TU: {unit}")
        return lines
    return []


def cmd_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(
        args.workspace,
        ffmpeg_root=args.ffmpeg_root,
        ffmpeg_search_roots=args.ffmpeg_search_root,
    ).to_dict()
    if args.format == "json":
        _write(_json(report), args.output)
    else:
        _write(_text_doctor(report), args.output)
    return 0 if report["ok"] else 1


def _text_storage_info(info: dict[str, Any]) -> str:
    lines = [
        "Code Expositor storage",
        f"- path: {info['path']}",
        f"- exists: {info['exists']}",
        f"- initialized: {info['initialized']}",
        f"- ok: {info['ok']}",
    ]
    counts = info.get("counts") or {}
    if counts:
        lines.append("")
        lines.append("Counts")
        for key, value in sorted(counts.items()):
            lines.append(f"- {key}: {value}")
    adjacency = info.get("adjacency_counts") or {}
    if adjacency:
        lines.append("")
        lines.append("Adjacency")
        for key, value in sorted(adjacency.items()):
            lines.append(f"- {key}: {value}")
    edge_types = info.get("edge_type_counts") or {}
    if edge_types:
        lines.append("")
        lines.append("Edge Types")
        for key, value in sorted(edge_types.items()):
            lines.append(f"- {key}: {value}")
    issues = info.get("issues") or []
    if issues:
        lines.append("")
        lines.append("Issues")
        lines.extend(f"- {item}" for item in issues)
    return "\n".join(lines) + "\n"


def cmd_store_info(args: argparse.Namespace) -> int:
    info = storage_info(args.db)
    if args.format == "json":
        _write(_json(info), args.output)
    else:
        _write(_text_storage_info(info), args.output)
    return 0 if info["ok"] else 1


def _require_explain_value(args: argparse.Namespace) -> str:
    if not args.value:
        raise SystemExit(f"explain {args.subject} requires --value")
    return args.value


def _where_implemented(graph: Graph, symbol: str) -> dict[str, Any]:
    matches = [
        node
        for node in graph.nodes.values()
        if node.type in {"Function", "Method", "Symbol"}
        and (node.label == symbol or node.label.endswith(f"::{symbol}"))
        and (node.metadata.get("definition") or node.metadata.get("unresolved"))
    ]
    matches.sort(key=lambda item: (item.path or "", item.metadata.get("line", 0), item.label))
    query = QueryEngine(graph)
    return {
        "symbol": symbol,
        "definitions": [node.to_dict() for node in matches],
        "evidence": [query.evidence_for(node.id) for node in matches],
    }


def _non_repository_explanation_payload(graph: Graph, args: argparse.Namespace) -> dict[str, Any]:
    query = QueryEngine(graph)
    subject = args.subject
    value = _require_explain_value(args)
    if subject == "module":
        graph_query = "module_summary"
        question = f"What does module {value} contain?"
        result = query.module_summary(value)
    elif subject == "file":
        graph_query = "file_summary"
        question = f"What graph evidence describes file {value}?"
        result = query.file_summary(value)
    elif subject == "function":
        graph_query = "function_summary"
        question = f"What graph evidence describes function {value}?"
        result = {
            "function": value,
            "callers": query.callers_of(value)["callers"],
            "callees": query.callees_of(value)["callees"],
            "evidence": query.evidence_for(value),
        }
    elif subject == "path":
        if args.target:
            graph_query = "paths_from"
            question = f"What static call path connects {value} to {args.target}?"
            result = query.paths_from(value, args.target, max_depth=args.max_depth)
        else:
            graph_query = "paths_to"
            question = f"What static call paths reach {value}?"
            result = query.paths_to(value, max_depth=args.max_depth)
    elif subject == "architecture":
        graph_query = "architecture_slice"
        question = f"What files are architecture-specific for {value}?"
        result = query.architecture_slice(value)
    elif subject == "where":
        graph_query = "where_implemented"
        question = f"Where is {value} implemented?"
        result = _where_implemented(graph, value)
    else:
        raise ValueError(subject)
    return build_explanation_payload(
        question=question,
        graph_query=graph_query,
        query_result=result,
        graph=graph,
    )


def cmd_explain(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    if args.subject == "repository":
        if args.format == "payload":
            _write(_json(build_repository_evidence_payload(graph)), args.output)
            return 0
        explanation = build_top_down_explanation(graph)
        if args.format == "json":
            _write(_json(explanation), args.output)
        else:
            _write(render_top_down_explanation(explanation) + "\n", args.output)
        return 0

    payload = _non_repository_explanation_payload(graph, args)
    if args.format in {"json", "payload"}:
        _write(_json(payload), args.output)
    else:
        _write(render_explanation(payload) + "\n", args.output)
    return 0


def _text_edges(title: str, rows: list[dict[str, Any]]) -> str:
    lines = [title]
    if not rows:
        lines.append("No matching graph edges.")
        return "\n".join(lines) + "\n"
    for row in rows:
        edge = row["edge"]
        source = row["source"]
        target = row["target"]
        evidence = edge.get("evidence") or []
        location = ""
        if evidence:
            first = evidence[0]
            location = f" ({first.get('path')}:{first.get('line')})"
        lines.append(
            f"- {source['label']} -> {target['label']} "
            f"[{edge['type']} {edge['confidence']}]{location}"
        )
    return "\n".join(lines) + "\n"


def _text_nodes(title: str, rows: list[dict[str, Any]]) -> str:
    lines = [title]
    if not rows:
        lines.append("No matching graph nodes.")
        return "\n".join(lines) + "\n"
    for row in rows:
        location = row.get("path") or ""
        line = (row.get("metadata") or {}).get("line")
        if line:
            location = f"{location}:{line}"
        suffix = f" {location}".rstrip()
        lines.append(f"- {row['label']} [{row['type']}]{suffix}")
    return "\n".join(lines) + "\n"


def cmd_callers(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    result = QueryEngine(graph).callers_of(args.function)
    if args.format == "json":
        _write(_json(result), args.output)
    else:
        _write(_text_edges(f"Callers of {args.function}", result["callers"]), args.output)
    return 0


def cmd_callees(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    result = QueryEngine(graph).callees_of(args.function)
    if args.format == "json":
        _write(_json(result), args.output)
    else:
        _write(_text_edges(f"Callees of {args.function}", result["callees"]), args.output)
    return 0


def cmd_public_api(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    result = QueryEngine(graph).public_api(args.module)
    if args.format == "json":
        _write(_json(result), args.output)
    else:
        _write(_text_nodes(f"Public API in {args.module}", result["public_api"]), args.output)
    return 0


def cmd_includes_of(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    result = QueryEngine(graph).includes_of(args.file)
    if args.format == "json":
        _write(_json(result), args.output)
    else:
        _write(_text_edges(f"Includes of {args.file}", result["includes"]), args.output)
    return 0


def cmd_dependents_of(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    result = QueryEngine(graph).dependents_of(args.path)
    if args.format == "json":
        _write(_json(result), args.output)
    else:
        _write(_text_edges(f"Dependents of {args.path}", result["dependents"]), args.output)
    return 0


def _text_paths(title: str, paths: list[list[dict[str, Any]]]) -> str:
    lines = [title]
    if not paths:
        lines.append("No static path found.")
        return "\n".join(lines) + "\n"
    for path in paths:
        lines.append("- " + " -> ".join(node["label"] for node in path))
    return "\n".join(lines) + "\n"


def _path_result_graph(graph: Graph, paths: list[list[dict[str, Any]]]) -> Graph:
    selected = Graph()
    node_ids = {node["id"] for path in paths for node in path}
    for node_id in node_ids:
        selected.nodes[node_id] = graph.nodes[node_id]

    for path in paths:
        for source, target in zip(path, path[1:]):
            for edge in graph.edges.values():
                if edge.source == source["id"] and edge.target == target["id"]:
                    selected.edges[edge.id] = edge
                    break
    return selected


def cmd_paths_to(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    result = QueryEngine(graph).paths_to(args.function, max_depth=args.max_depth)
    if args.format == "json":
        _write(_json(result), args.output)
    elif args.format == "svg":
        _write(graph_to_svg(_path_result_graph(graph, result["paths"]), "calls"), args.output)
    else:
        _write(_text_paths(f"Paths to {args.function}", result["paths"]), args.output)
    return 0


def cmd_paths_from(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    result = QueryEngine(graph).paths_from(
        args.entrypoint,
        args.target,
        max_depth=args.max_depth,
    )
    if args.format == "json":
        _write(_json(result), args.output)
    elif args.format == "svg":
        _write(graph_to_svg(_path_result_graph(graph, result["paths"]), "calls"), args.output)
    else:
        _write(
            _text_paths(f"Paths from {args.entrypoint} to {args.target}", result["paths"]),
            args.output,
        )
    return 0


def cmd_why_reachable(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    result = QueryEngine(graph).why_reachable(args.function)
    if args.format == "json":
        _write(_json(result), args.output)
    else:
        lines = [_text_paths(f"Why {args.function} is reachable", result["paths"]).rstrip()]
        lines.append("")
        lines.append(_text_edges("Direct callers", result["callers"]).rstrip())
        _write("\n".join(lines) + "\n", args.output)
    return 0


def cmd_evidence_for(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    result = QueryEngine(graph).evidence_for(args.target)
    if args.format == "json":
        _write(_json(result), args.output)
    else:
        target = result.get("target")
        lines = [f"Evidence for {args.target}"]
        if isinstance(target, dict):
            if "label" in target:
                lines.append(f"- target: {target['label']} [{target.get('type', '')}]")
            elif "type" in target:
                lines.append(f"- edge: {target.get('type')} {target.get('confidence', '')}")
        related = result.get("related_edges") or []
        evidence = result.get("evidence") or []
        if related:
            lines.append(f"- related edges: {len(related)}")
            for edge in related[:12]:
                lines.append(
                    f"  - {edge.get('type')} {edge.get('confidence')} via {edge.get('extraction_tool')}"
                )
        if evidence:
            for item in evidence:
                location = item.get("path", "")
                if item.get("line"):
                    location = f"{location}:{item['line']}"
                lines.append(f"- {location} {item.get('snippet') or ''}".rstrip())
        if not related and not evidence:
            lines.append("- No evidence selected.")
        _write("\n".join(lines) + "\n", args.output)
    return 0


def _text_mpeg4_case_study(result: dict[str, Any]) -> str:
    lines = [result["question"], ""]
    lines.append("Matching files")
    if result["matching_files"]:
        for item in result["matching_files"]:
            lines.append(f"- {item['file']} ({', '.join(item['evidence'])})")
    else:
        lines.append("- None")

    lines.extend(["", "Implementation candidates"])
    if result.get("implementation_candidates"):
        for item in result["implementation_candidates"]:
            location = item.get("path") or ""
            if item.get("line"):
                location = f"{location}:{item['line']}"
            basis = ", ".join(item.get("match_basis") or [])
            suffix = f" ({basis})" if basis else ""
            score = item.get("rank_score")
            score_suffix = f", score={score}" if score is not None else ""
            lines.append(
                f"- {item['symbol']} [{item['type']} {item['role']}{score_suffix}] {location}{suffix}".rstrip()
            )
    else:
        lines.append("- None")

    lines.extend(["", "Matching symbols"])
    if result["matching_symbols"]:
        for item in result["matching_symbols"]:
            location = item.get("path") or ""
            line = (item.get("metadata") or {}).get("line")
            if line:
                location = f"{location}:{line}"
            lines.append(f"- {item['label']} [{item['type']}] {location}".rstrip())
    else:
        lines.append("- None")

    lines.extend(["", "Public API candidates"])
    if result["public_api_candidates"]:
        for item in result["public_api_candidates"]:
            location = item.get("path") or ""
            line = (item.get("metadata") or {}).get("line")
            if line:
                location = f"{location}:{line}"
            lines.append(f"- {item['label']} [{item['type']}] {location}".rstrip())
    else:
        lines.append("- None")

    lines.extend(["", "Direct callers"])
    any_callers = False
    for symbol, callers in result["direct_callers"].items():
        for row in callers:
            any_callers = True
            lines.append(f"- {row['source']['label']} -> {symbol} [{row['edge']['confidence']}]")
    if not any_callers:
        lines.append("- None")

    lines.extend(["", "Possible static paths"])
    any_paths = False
    for symbol, paths in result["possible_paths"].items():
        for path in paths:
            any_paths = True
            lines.append(f"- {symbol}: " + " -> ".join(node["label"] for node in path))
    if not any_paths:
        lines.append("- None")

    lines.extend(["", "Limitations"])
    lines.extend(f"- {item}" for item in result["limitations"])
    return "\n".join(lines) + "\n"


def cmd_case_study(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    if args.study != "mpeg4":
        raise ValueError(args.study)
    result = run_mpeg4_case_study(graph, max_depth=args.max_depth)
    if args.format == "json":
        _write(_json(result), args.output)
    else:
        _write(_text_mpeg4_case_study(result), args.output)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    if not args.html:
        _write(_json(QueryEngine(graph).repo_summary()), args.output)
        return 0
    output = args.output or "expositor-report.html"
    _write(render_html_report(graph), output)
    if not args.output:
        sys.stdout.write(f"Wrote {output}\n")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    if args.export_format == "dot":
        _write(graph_to_dot(graph, args.graph), args.output)
    elif args.export_format == "svg":
        _write(graph_to_svg(graph, args.graph, renderer=args.renderer), args.output)
    else:
        raise ValueError(args.export_format)
    return 0


def cmd_indexes(args: argparse.Namespace) -> int:
    _write(
        _json(
            build_indexes(
                args.repo,
                outline_source=args.outline_source,
                symbol_source=args.symbol_source,
            ).to_dict()
        ),
        args.output,
    )
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    graph = _load_or_build_graph(
        args.repo,
        args.db,
        semantic=args.semantic,
        semantic_limit=args.semantic_limit,
        outline_source=args.outline_source,
        symbol_source=args.symbol_source,
    )
    query = QueryEngine(graph)
    name = args.query_name
    value = args.value or ""
    if name != "repo-summary" and not value:
        raise SystemExit(f"query {name} requires --value")

    if name == "repo-summary":
        result = query.repo_summary()
    elif name == "module-summary":
        result = query.module_summary(value)
    elif name == "file-summary":
        result = query.file_summary(value)
    elif name == "symbols-in":
        result = query.symbols_in(value)
    elif name == "public-api":
        result = query.public_api(value)
    elif name == "includes-of":
        result = query.includes_of(value)
    elif name == "dependents-of":
        result = query.dependents_of(value)
    elif name == "callers-of":
        result = query.callers_of(value)
    elif name == "callees-of":
        result = query.callees_of(value)
    elif name == "paths-to":
        result = query.paths_to(value, max_depth=args.max_depth)
    elif name == "paths-from":
        if not args.target:
            raise SystemExit("query paths-from requires --target")
        result = query.paths_from(value, args.target, max_depth=args.max_depth)
    elif name == "architecture-slice":
        result = query.architecture_slice(value)
    elif name == "why-reachable":
        result = query.why_reachable(value)
    elif name == "evidence-for":
        result = query.evidence_for(value)
    else:
        raise ValueError(name)

    _write(_json(result), args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="expositor", description="Code Expositor CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_repo(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("repo", nargs="?", default=".", help="repository path")
        subparser.add_argument("--output", "-o", help="write output to file")

    def add_graph_build_options(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--semantic", action="store_true", help="merge optional Clang AST semantic facts")
        subparser.add_argument("--semantic-limit", type=int, help="limit semantic translation units")
        subparser.add_argument(
            "--outline-source",
            choices=["regex", "tree-sitter", "auto"],
            default="regex",
            help="outline extraction source for graph-building commands",
        )
        subparser.add_argument(
            "--symbol-source",
            choices=["outline", "ctags", "auto"],
            default="outline",
            help="symbol extraction source for graph-building commands",
        )

    schema = subparsers.add_parser("schema", help="emit canonical graph schema")
    schema.add_argument("--output", "-o", help="write output to file")
    schema.set_defaults(func=cmd_schema)

    scan = subparsers.add_parser("scan", help="scan repository inventory")
    add_repo(scan)
    scan.set_defaults(func=cmd_scan)

    outline = subparsers.add_parser("outline", help="extract rough code outline")
    add_repo(outline)
    outline.add_argument(
        "--source",
        choices=["regex", "tree-sitter", "auto"],
        default="auto",
        help="outline extraction source",
    )
    outline.set_defaults(func=cmd_outline)

    symbols = subparsers.add_parser("symbols", help="build symbol index")
    add_repo(symbols)
    symbols.add_argument(
        "--source",
        choices=["auto", "outline", "ctags"],
        default="auto",
        help="symbol extraction source",
    )
    symbols.add_argument(
        "--outline-source",
        choices=["regex", "tree-sitter", "auto"],
        default="auto",
        help="outline extraction source when symbol source uses outline",
    )
    symbols.set_defaults(func=cmd_symbols)

    includes = subparsers.add_parser("includes", help="build include graph")
    add_repo(includes)
    includes.set_defaults(func=cmd_includes)

    build_context = subparsers.add_parser("build-context", help="load or capture build context")
    add_repo(build_context)
    build_context.add_argument(
        "--make-target",
        action="append",
        help="capture a compile command from `make -n V=1 TARGET`; can be provided multiple times",
    )
    build_context.add_argument(
        "--write-compile-commands",
        help="write captured commands to this compile_commands.json path",
    )
    build_context.set_defaults(func=cmd_build_context)

    architecture = subparsers.add_parser("architecture", help="classify architecture-specific files")
    add_repo(architecture)
    architecture.set_defaults(func=cmd_architecture)

    semantic = subparsers.add_parser("semantic", help="run optional Clang AST semantic spike")
    add_repo(semantic)
    semantic.add_argument("--limit", type=int, help="limit translation units")
    semantic.set_defaults(func=cmd_semantic)

    graph = subparsers.add_parser("graph", help="build canonical graph")
    add_repo(graph)
    add_graph_build_options(graph)
    graph.add_argument("--db", help="write graph to SQLite database")
    graph.set_defaults(func=cmd_graph)

    validate = subparsers.add_parser("validate", help="validate canonical graph quality")
    validate.add_argument("repo", nargs="?", default=".")
    validate.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(validate)
    validate.add_argument("--format", choices=["text", "json"], default="text")
    validate.add_argument("--output", "-o")
    validate.set_defaults(func=cmd_validate)

    doctor = subparsers.add_parser("doctor", help="audit local milestone readiness")
    doctor.add_argument("workspace", nargs="?", default=".")
    doctor.add_argument("--ffmpeg-root", help="explicit FFmpeg checkout path")
    doctor.add_argument(
        "--ffmpeg-search-root",
        action="append",
        help="directory to search for FFmpeg checkouts; can be provided multiple times",
    )
    doctor.add_argument("--format", choices=["text", "json"], default="text")
    doctor.add_argument("--output", "-o")
    doctor.set_defaults(func=cmd_doctor)

    store_info = subparsers.add_parser("store-info", help="inspect a SQLite graph store")
    store_info.add_argument("db", help="SQLite graph database path")
    store_info.add_argument("--format", choices=["text", "json"], default="text")
    store_info.add_argument("--output", "-o")
    store_info.set_defaults(func=cmd_store_info)

    indexes = subparsers.add_parser("indexes", help="emit all core indexes")
    add_repo(indexes)
    indexes.add_argument(
        "--outline-source",
        choices=["regex", "tree-sitter", "auto"],
        default="regex",
        help="outline extraction source",
    )
    indexes.add_argument(
        "--symbol-source",
        choices=["outline", "ctags", "auto"],
        default="outline",
        help="symbol extraction source",
    )
    indexes.set_defaults(func=cmd_indexes)

    query = subparsers.add_parser("query", help="run a structured Query API call")
    query.add_argument(
        "query_name",
        choices=[
            "repo-summary",
            "module-summary",
            "file-summary",
            "symbols-in",
            "public-api",
            "includes-of",
            "dependents-of",
            "callers-of",
            "callees-of",
            "paths-to",
            "paths-from",
            "architecture-slice",
            "why-reachable",
            "evidence-for",
        ],
    )
    query.add_argument("repo", nargs="?", default=".")
    query.add_argument("--value", help="path, module, function, architecture or id argument")
    query.add_argument("--target", help="target function for paths-from")
    query.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(query)
    query.add_argument("--max-depth", type=int, default=8)
    query.add_argument("--output", "-o")
    query.set_defaults(func=cmd_query)

    explain = subparsers.add_parser("explain", help="generate evidence-bound explanation")
    explain.add_argument(
        "subject",
        choices=["repository", "module", "file", "function", "path", "architecture", "where"],
    )
    explain.add_argument("repo", nargs="?", default=".")
    explain.add_argument("--value", help="module, file, function, architecture or symbol to explain")
    explain.add_argument("--target", help="target function for path explanations")
    explain.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(explain)
    explain.add_argument("--max-depth", type=int, default=8)
    explain.add_argument("--format", choices=["text", "json", "payload"], default="text")
    explain.add_argument("--output", "-o")
    explain.set_defaults(func=cmd_explain)

    callers = subparsers.add_parser("callers", help="show callers of a function")
    callers.add_argument("function")
    callers.add_argument("repo", nargs="?", default=".")
    callers.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(callers)
    callers.add_argument("--format", choices=["text", "json"], default="text")
    callers.add_argument("--output", "-o")
    callers.set_defaults(func=cmd_callers)

    callees = subparsers.add_parser("callees", help="show callees of a function")
    callees.add_argument("function")
    callees.add_argument("repo", nargs="?", default=".")
    callees.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(callees)
    callees.add_argument("--format", choices=["text", "json"], default="text")
    callees.add_argument("--output", "-o")
    callees.set_defaults(func=cmd_callees)

    public_api = subparsers.add_parser("public-api", help="show public API symbols for a module")
    public_api.add_argument("module")
    public_api.add_argument("repo", nargs="?", default=".")
    public_api.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(public_api)
    public_api.add_argument("--format", choices=["text", "json"], default="text")
    public_api.add_argument("--output", "-o")
    public_api.set_defaults(func=cmd_public_api)

    includes_of = subparsers.add_parser("includes-of", help="show include dependencies of a file")
    includes_of.add_argument("file")
    includes_of.add_argument("repo", nargs="?", default=".")
    includes_of.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(includes_of)
    includes_of.add_argument("--format", choices=["text", "json"], default="text")
    includes_of.add_argument("--output", "-o")
    includes_of.set_defaults(func=cmd_includes_of)

    dependents_of = subparsers.add_parser("dependents-of", help="show files or modules depending on a path")
    dependents_of.add_argument("path")
    dependents_of.add_argument("repo", nargs="?", default=".")
    dependents_of.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(dependents_of)
    dependents_of.add_argument("--format", choices=["text", "json"], default="text")
    dependents_of.add_argument("--output", "-o")
    dependents_of.set_defaults(func=cmd_dependents_of)

    paths_to = subparsers.add_parser("paths-to", help="show possible static paths to a function")
    paths_to.add_argument("function")
    paths_to.add_argument("repo", nargs="?", default=".")
    paths_to.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(paths_to)
    paths_to.add_argument("--max-depth", type=int, default=8)
    paths_to.add_argument("--format", choices=["text", "json", "svg"], default="text")
    paths_to.add_argument("--output", "-o")
    paths_to.set_defaults(func=cmd_paths_to)

    paths_from = subparsers.add_parser("paths-from", help="show possible static paths from one function to another")
    paths_from.add_argument("entrypoint")
    paths_from.add_argument("target")
    paths_from.add_argument("repo", nargs="?", default=".")
    paths_from.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(paths_from)
    paths_from.add_argument("--max-depth", type=int, default=8)
    paths_from.add_argument("--format", choices=["text", "json", "svg"], default="text")
    paths_from.add_argument("--output", "-o")
    paths_from.set_defaults(func=cmd_paths_from)

    why_reachable = subparsers.add_parser("why-reachable", help="explain static reachability evidence for a function")
    why_reachable.add_argument("function")
    why_reachable.add_argument("repo", nargs="?", default=".")
    why_reachable.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(why_reachable)
    why_reachable.add_argument("--format", choices=["text", "json"], default="text")
    why_reachable.add_argument("--output", "-o")
    why_reachable.set_defaults(func=cmd_why_reachable)

    evidence_for = subparsers.add_parser("evidence-for", help="show graph evidence for a node, edge, label or path")
    evidence_for.add_argument("target")
    evidence_for.add_argument("repo", nargs="?", default=".")
    evidence_for.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(evidence_for)
    evidence_for.add_argument("--format", choices=["text", "json"], default="text")
    evidence_for.add_argument("--output", "-o")
    evidence_for.set_defaults(func=cmd_evidence_for)

    case_study = subparsers.add_parser("case-study", help="run an evidence-bound case study")
    case_study.add_argument("study", choices=["mpeg4"])
    case_study.add_argument("repo", nargs="?", default=".")
    case_study.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(case_study)
    case_study.add_argument("--max-depth", type=int, default=8)
    case_study.add_argument("--format", choices=["text", "json"], default="text")
    case_study.add_argument("--output", "-o")
    case_study.set_defaults(func=cmd_case_study)

    report = subparsers.add_parser("report", help="generate report")
    report.add_argument("repo", nargs="?", default=".")
    report.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(report)
    report.add_argument("--html", action="store_true", help="write static HTML report")
    report.add_argument("--output", "-o")
    report.set_defaults(func=cmd_report)

    export = subparsers.add_parser("export", help="export graph")
    export.add_argument("export_format", choices=["dot", "svg"])
    export.add_argument("repo", nargs="?", default=".")
    export.add_argument("--db", help="load or save SQLite graph")
    add_graph_build_options(export)
    export.add_argument("--graph", choices=["includes", "calls", "modules", "architecture", "all"], default="all")
    export.add_argument(
        "--renderer",
        choices=["auto", "internal", "graphviz"],
        default="auto",
        help="SVG renderer",
    )
    export.add_argument("--output", "-o")
    export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
