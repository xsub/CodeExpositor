"""MPEG-4 evidence case study."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from expositor.model import EdgeType, Graph, NodeType
from expositor.queries import QueryEngine


MPEG4_RE = re.compile(r"mpeg[-_ ]?4|mp4v", re.IGNORECASE)
DECODE_RE = re.compile(r"decode|decoder|videodec|_dec(?:_|$)|decod", re.IGNORECASE)
MACRO_LIKE_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")


def _matches(value: str | None) -> bool:
    return bool(value and MPEG4_RE.search(value))


def _symbol_role(node: Any) -> str:
    metadata = node.metadata or {}
    if metadata.get("definition"):
        return "definition"
    if metadata.get("declaration"):
        return "declaration"
    if metadata.get("unresolved"):
        return "unresolved"
    return "candidate"


def _candidate_basis(node: Any) -> list[str]:
    label = node.label or ""
    path = node.path or ""
    path_lower = path.lower()
    basis = []
    label_matches_mpeg4 = _matches(label)
    label_matches_decode = bool(DECODE_RE.search(label))
    path_matches_mpeg4 = _matches(path)
    path_matches_decode = bool(DECODE_RE.search(path))
    if label_matches_mpeg4:
        basis.append("symbol-name")
    if path_matches_mpeg4:
        basis.append("symbol-path")
    if label_matches_decode:
        basis.append("decode-name")
    if path_matches_decode:
        basis.append("decode-path")
    if (path_matches_mpeg4 or path_matches_decode) and not (
        label_matches_mpeg4 or label_matches_decode
    ):
        basis.append("path-only-symbol")
    if "mpeg4videodec" in path_lower:
        basis.append("mpeg4-video-decoder-path")
    if path_lower.startswith("libavcodec/"):
        basis.append("libavcodec-path")
    if node.type in {NodeType.FUNCTION.value, NodeType.METHOD.value}:
        basis.append("callable-symbol")
    if MACRO_LIKE_RE.match(label):
        basis.append("macro-like-name")
    return basis


def _candidate_score(node: Any, role: str, basis: list[str]) -> int:
    weights = {
        "symbol-name": 6,
        "symbol-path": 2,
        "decode-name": 6,
        "decode-path": 4,
        "mpeg4-video-decoder-path": 8,
        "libavcodec-path": 2,
        "callable-symbol": 5,
        "macro-like-name": -12,
        "path-only-symbol": -8,
    }
    score = sum(weights.get(item, 0) for item in basis)
    if role == "definition":
        score += 10
    elif role == "declaration":
        score += 1
    elif role == "unresolved":
        score -= 4
    return score


def _implementation_candidates(nodes: list[Any]) -> list[dict[str, Any]]:
    candidates = []
    for node in nodes:
        metadata = node.metadata or {}
        role = _symbol_role(node)
        match_basis = _candidate_basis(node)
        candidates.append(
            {
                "symbol": node.label,
                "type": node.type,
                "path": node.path,
                "line": metadata.get("line"),
                "role": role,
                "match_basis": match_basis,
                "rank_score": _candidate_score(node, role, match_basis),
                "node": node.to_dict(),
            }
        )
    role_order = {"definition": 0, "candidate": 1, "declaration": 2, "unresolved": 3}
    return sorted(
        candidates,
        key=lambda item: (
            -int(item["rank_score"]),
            role_order.get(str(item["role"]), 99),
            str(item["path"] or ""),
            item["line"] or 0,
            str(item["symbol"]),
        ),
    )


def run_mpeg4_case_study(graph: Graph, max_depth: int = 8) -> dict[str, Any]:
    query = QueryEngine(graph)
    matching_symbols = [
        node
        for node in graph.nodes.values()
        if node.type in {NodeType.FUNCTION.value, NodeType.METHOD.value, NodeType.SYMBOL.value}
        and (_matches(node.label) or _matches(node.path))
    ]
    matching_files = [
        node
        for node in graph.nodes.values()
        if node.type in {NodeType.SOURCE_FILE.value, NodeType.HEADER_FILE.value, NodeType.FILE.value}
        and (_matches(node.label) or _matches(node.path))
    ]

    files_by_evidence: dict[str, set[str]] = defaultdict(set)
    for symbol in matching_symbols:
        if symbol.path:
            files_by_evidence[symbol.path].add(f"symbol:{symbol.label}")
    for file_node in matching_files:
        if file_node.path:
            files_by_evidence[file_node.path].add("path-or-filename")

    direct_callers: dict[str, Any] = {}
    possible_paths: dict[str, Any] = {}
    for symbol in matching_symbols:
        direct_callers[symbol.label] = query.callers_of(symbol.label)["callers"]
        possible_paths[symbol.label] = query.paths_to(symbol.label, max_depth=max_depth)["paths"]

    public_api_candidates = [
        node
        for node in graph.nodes_of_type(NodeType.PUBLIC_API)
        if _matches(node.label) or _matches(node.path)
    ]
    if not public_api_candidates:
        for edge in graph.edges_of_type(EdgeType.CALLS, EdgeType.MAY_CALL):
            target = graph.nodes[edge.target]
            source = graph.nodes[edge.source]
            if target.id in {node.id for node in matching_symbols}:
                public_api_candidates.append(source)

    return {
        "question": "Where is MPEG-4 decoding implemented?",
        "matching_symbols": [node.to_dict() for node in sorted(matching_symbols, key=lambda item: (item.path or "", item.label))],
        "implementation_candidates": _implementation_candidates(matching_symbols),
        "matching_files": [
            {"file": file, "evidence": sorted(evidence)}
            for file, evidence in sorted(files_by_evidence.items())
        ],
        "public_api_candidates": [
            node.to_dict()
            for node in sorted(
                {node.id: node for node in public_api_candidates}.values(),
                key=lambda item: (item.path or "", item.label),
            )
        ],
        "direct_callers": direct_callers,
        "possible_paths": possible_paths,
        "limitations": [
            "This case study is graph-evidence based and does not prove runtime execution.",
            "Indirect calls require later semantic and callback analysis to improve coverage.",
        ],
    }
