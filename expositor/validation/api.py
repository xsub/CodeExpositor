"""Quality gates for the canonical graph."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from expositor.model import Confidence, EdgeType, Graph, NodeType


ERROR = "error"
WARNING = "warning"

EVIDENCE_EDGE_TYPES = {
    EdgeType.DECLARES.value,
    EdgeType.DEFINES.value,
    EdgeType.INCLUDES.value,
    EdgeType.DEPENDS_ON.value,
    EdgeType.CALLS.value,
    EdgeType.MAY_CALL.value,
    EdgeType.UNRESOLVED.value,
    EdgeType.ARCH_SPECIFIC.value,
    EdgeType.EXPORTED_BY.value,
}

SOURCE_BOUND_EDGE_TYPES = {
    EdgeType.DECLARES.value,
    EdgeType.DEFINES.value,
    EdgeType.INCLUDES.value,
    EdgeType.CALLS.value,
    EdgeType.MAY_CALL.value,
    EdgeType.UNRESOLVED.value,
    EdgeType.ARCH_SPECIFIC.value,
}


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    subject: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "subject": self.subject,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    issue_counts: dict[str, int]
    graph_counts: dict[str, int]
    issues: list[ValidationIssue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issue_counts": self.issue_counts,
            "graph_counts": self.graph_counts,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _issue(
    issues: list[ValidationIssue],
    severity: str,
    code: str,
    message: str,
    subject: str,
    **metadata: Any,
) -> None:
    issues.append(
        ValidationIssue(
            severity=severity,
            code=code,
            message=message,
            subject=subject,
            metadata=metadata,
        )
    )


def _known_values(enum_type: type[NodeType] | type[EdgeType] | type[Confidence]) -> set[str]:
    return {item.value for item in enum_type}


def _validate_evidence(
    graph: Graph,
    issues: list[ValidationIssue],
) -> None:
    source_files = {
        node.path
        for node in graph.nodes.values()
        if node.type in {NodeType.SOURCE_FILE.value, NodeType.HEADER_FILE.value}
        and node.path
    }
    translation_units = {
        node.path
        for node in graph.nodes.values()
        if node.type == NodeType.TRANSLATION_UNIT.value and node.path
    }

    for edge in graph.edges.values():
        if edge.type in EVIDENCE_EDGE_TYPES and not edge.evidence:
            _issue(
                issues,
                WARNING,
                "edge_missing_evidence",
                "Edge should carry source evidence when available.",
                edge.id,
                edge_type=edge.type,
            )
            continue

        for evidence in edge.evidence:
            if not evidence.path:
                _issue(
                    issues,
                    WARNING,
                    "evidence_missing_path",
                    "Evidence item has no file path.",
                    edge.id,
                    edge_type=edge.type,
                )
            if evidence.line is not None and evidence.line < 1:
                _issue(
                    issues,
                    ERROR,
                    "evidence_invalid_line",
                    "Evidence line must be a positive integer.",
                    edge.id,
                    edge_type=edge.type,
                    path=evidence.path,
                    line=evidence.line,
                )

        if (
            edge.type in SOURCE_BOUND_EDGE_TYPES
            and edge.source in graph.nodes
            and graph.nodes[edge.source].path in translation_units
            and not edge.build_context
        ):
            _issue(
                issues,
                WARNING,
                "edge_missing_build_context",
                "Source-bound edge from a compiled file should carry build context.",
                edge.id,
                edge_type=edge.type,
                source_path=graph.nodes[edge.source].path,
            )
        if (
            edge.type in SOURCE_BOUND_EDGE_TYPES
            and edge.build_context
            and source_files
            and edge.build_context not in source_files
        ):
            _issue(
                issues,
                WARNING,
                "edge_unknown_build_context",
                "Edge build context does not match a known source or header file.",
                edge.id,
                edge_type=edge.type,
                build_context=edge.build_context,
            )


def validate_graph(graph: Graph) -> ValidationReport:
    """Validate canonical graph integrity and quality metadata."""

    issues: list[ValidationIssue] = []
    node_types = _known_values(NodeType)
    edge_types = _known_values(EdgeType)
    confidences = _known_values(Confidence)

    for node in graph.nodes.values():
        if not node.id:
            _issue(issues, ERROR, "node_missing_id", "Node has no id.", "<node>")
        if node.type not in node_types:
            _issue(
                issues,
                ERROR,
                "node_unknown_type",
                "Node type is not part of the canonical graph schema.",
                node.id,
                node_type=node.type,
            )
        if not node.label:
            _issue(
                issues,
                WARNING,
                "node_missing_label",
                "Node has no display label.",
                node.id,
                node_type=node.type,
            )

    for edge in graph.edges.values():
        if not edge.id:
            _issue(issues, ERROR, "edge_missing_id", "Edge has no id.", "<edge>")
        if edge.source not in graph.nodes:
            _issue(
                issues,
                ERROR,
                "edge_missing_source",
                "Edge source does not exist in the graph.",
                edge.id,
                source=edge.source,
            )
        if edge.target not in graph.nodes:
            _issue(
                issues,
                ERROR,
                "edge_missing_target",
                "Edge target does not exist in the graph.",
                edge.id,
                target=edge.target,
            )
        if edge.type not in edge_types:
            _issue(
                issues,
                ERROR,
                "edge_unknown_type",
                "Edge type is not part of the canonical graph schema.",
                edge.id,
                edge_type=edge.type,
            )
        if edge.confidence not in confidences:
            _issue(
                issues,
                ERROR,
                "edge_unknown_confidence",
                "Edge confidence is not part of the AI evidence contract.",
                edge.id,
                confidence=edge.confidence,
            )
        if not edge.extraction_tool:
            _issue(
                issues,
                ERROR,
                "edge_missing_extraction_tool",
                "Every graph edge must identify its extraction tool.",
                edge.id,
                edge_type=edge.type,
            )

    _validate_evidence(graph, issues)

    counts = Counter(issue.severity for issue in issues)
    graph_counts = {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
    }
    return ValidationReport(
        ok=counts[ERROR] == 0,
        issue_counts={ERROR: counts[ERROR], WARNING: counts[WARNING]},
        graph_counts=graph_counts,
        issues=issues,
    )
