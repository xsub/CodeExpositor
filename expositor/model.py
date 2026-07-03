"""Canonical graph model owned by Code Expositor."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
import hashlib
import json
from typing import Any, Iterable


INDEX_VERSION = "0.1"


class Confidence(str, Enum):
    CONFIRMED = "CONFIRMED"
    LIKELY = "LIKELY"
    POSSIBLE = "POSSIBLE"
    UNRESOLVED = "UNRESOLVED"
    OBSERVED_RUNTIME = "OBSERVED_RUNTIME"


class NodeType(str, Enum):
    REPOSITORY = "Repository"
    DIRECTORY = "Directory"
    FILE = "File"
    SOURCE_FILE = "SourceFile"
    HEADER_FILE = "HeaderFile"
    TRANSLATION_UNIT = "TranslationUnit"
    MODULE = "Module"
    LIBRARY = "Library"
    NAMESPACE = "Namespace"
    CLASS = "Class"
    STRUCT = "Struct"
    ENUM = "Enum"
    MACRO = "Macro"
    FUNCTION = "Function"
    METHOD = "Method"
    VARIABLE = "Variable"
    TYPEDEF = "Typedef"
    SYMBOL = "Symbol"
    CALLSITE = "CallSite"
    BUILD_TARGET = "BuildTarget"
    ARCHITECTURE = "Architecture"
    COMPILER_FLAG = "CompilerFlag"
    FEATURE_FLAG = "FeatureFlag"
    PUBLIC_API = "PublicAPI"
    ENTRYPOINT = "EntryPoint"


class EdgeType(str, Enum):
    CONTAINS = "CONTAINS"
    DECLARES = "DECLARES"
    DEFINES = "DEFINES"
    REFERENCES = "REFERENCES"
    INCLUDES = "INCLUDES"
    DEPENDS_ON = "DEPENDS_ON"
    CALLS = "CALLS"
    MAY_CALL = "MAY_CALL"
    UNRESOLVED = "UNRESOLVED"
    ASSIGNS_FUNCTION_POINTER = "ASSIGNS_FUNCTION_POINTER"
    USES_CALLBACK = "USES_CALLBACK"
    REGISTERED_AS = "REGISTERED_AS"
    COMPILED_IN = "COMPILED_IN"
    EXCLUDED_BY = "EXCLUDED_BY"
    ARCH_SPECIFIC = "ARCH_SPECIFIC"
    EXPORTED_BY = "EXPORTED_BY"
    ENTRY_REACHES = "ENTRY_REACHES"
    HAS_EVIDENCE = "HAS_EVIDENCE"


@dataclass(frozen=True)
class Evidence:
    path: str
    line: int | None = None
    column: int | None = None
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "snippet": self.snippet,
        }


@dataclass
class Node:
    id: str
    type: str
    label: str
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "path": self.path,
            "metadata": self.metadata,
        }


@dataclass
class Edge:
    id: str
    source: str
    target: str
    type: str
    confidence: str
    extraction_tool: str
    evidence: list[Evidence] = field(default_factory=list)
    build_context: str | None = None
    architecture_context: str | None = None
    index_version: str = INDEX_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "confidence": self.confidence,
            "extraction_tool": self.extraction_tool,
            "evidence": [item.to_dict() for item in self.evidence],
            "build_context": self.build_context,
            "architecture_context": self.architecture_context,
            "index_version": self.index_version,
            "metadata": self.metadata,
        }


def stable_id(*parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return digest[:24]


def enum_value(value: str | Enum) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _field_names(model: type[Any]) -> list[str]:
    return [item.name for item in fields(model)]


def graph_schema() -> dict[str, Any]:
    """Return the executable canonical graph schema for adapters and clients."""

    return {
        "project": "Code Expositor",
        "package": "expositor",
        "schema_owner": "Expositor Core",
        "index_version": INDEX_VERSION,
        "node_types": [item.value for item in NodeType],
        "edge_types": [item.value for item in EdgeType],
        "confidence_labels": [item.value for item in Confidence],
        "node_fields": _field_names(Node),
        "edge_fields": _field_names(Edge),
        "evidence_fields": _field_names(Evidence),
        "required_edge_fields": [
            "source",
            "target",
            "type",
            "confidence",
            "extraction_tool",
        ],
        "evidence_contract": {
            "graph_is_source_of_truth": True,
            "ai_may_explain_only_extracted_evidence": True,
            "confidence_labels": [item.value for item in Confidence],
        },
        "quality_requirements": [
            "Every extractor produces deterministic structured output.",
            "Every edge records source, target, type, confidence and extraction tool.",
            "Evidence locations are attached whenever an extractor can provide them.",
            "External tools feed or render the schema but do not define it.",
        ],
    }


class Graph:
    """In-memory canonical graph.

    This is intentionally small and serializable. External tools may feed it,
    but they do not define its schema.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}

    def add_node(
        self,
        node_type: str | NodeType,
        label: str,
        *,
        path: str | None = None,
        metadata: dict[str, Any] | None = None,
        node_id: str | None = None,
    ) -> Node:
        node_type_value = enum_value(node_type)
        resolved_id = node_id or stable_id("node", node_type_value, path, label)
        existing = self.nodes.get(resolved_id)
        if existing:
            if metadata:
                existing.metadata.update(metadata)
            if path and existing.path is None:
                existing.path = path
            return existing
        node = Node(
            id=resolved_id,
            type=node_type_value,
            label=label,
            path=path,
            metadata=dict(metadata or {}),
        )
        self.nodes[node.id] = node
        return node

    def add_edge(
        self,
        source: Node | str,
        target: Node | str,
        edge_type: str | EdgeType,
        *,
        confidence: str | Confidence = Confidence.CONFIRMED,
        extraction_tool: str,
        evidence: Iterable[Evidence] | None = None,
        build_context: str | None = None,
        architecture_context: str | None = None,
        metadata: dict[str, Any] | None = None,
        edge_id: str | None = None,
    ) -> Edge:
        source_id = source.id if isinstance(source, Node) else source
        target_id = target.id if isinstance(target, Node) else target
        edge_type_value = enum_value(edge_type)
        confidence_value = enum_value(confidence)
        evidence_list = list(evidence or [])
        evidence_key = [
            (item.path, item.line, item.column, item.snippet)
            for item in evidence_list
        ]
        resolved_id = edge_id or stable_id(
            "edge",
            edge_type_value,
            source_id,
            target_id,
            confidence_value,
            extraction_tool,
            json.dumps(evidence_key, sort_keys=True),
        )
        existing = self.edges.get(resolved_id)
        if existing:
            if metadata:
                existing.metadata.update(metadata)
            return existing
        edge = Edge(
            id=resolved_id,
            source=source_id,
            target=target_id,
            type=edge_type_value,
            confidence=confidence_value,
            extraction_tool=extraction_tool,
            evidence=evidence_list,
            build_context=build_context,
            architecture_context=architecture_context,
            metadata=dict(metadata or {}),
        )
        self.edges[edge.id] = edge
        return edge

    def edges_of_type(self, *edge_types: str | EdgeType) -> list[Edge]:
        wanted = {enum_value(edge_type) for edge_type in edge_types}
        return [edge for edge in self.edges.values() if edge.type in wanted]

    def nodes_of_type(self, *node_types: str | NodeType) -> list[Node]:
        wanted = {enum_value(node_type) for node_type in node_types}
        return [node for node in self.nodes.values() if node.type in wanted]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_version": INDEX_VERSION,
            "nodes": [self.nodes[key].to_dict() for key in sorted(self.nodes)],
            "edges": [self.edges[key].to_dict() for key in sorted(self.edges)],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Graph":
        graph = cls()
        for item in payload.get("nodes", []):
            graph.nodes[item["id"]] = Node(
                id=item["id"],
                type=item["type"],
                label=item["label"],
                path=item.get("path"),
                metadata=dict(item.get("metadata") or {}),
            )
        for item in payload.get("edges", []):
            graph.edges[item["id"]] = Edge(
                id=item["id"],
                source=item["source"],
                target=item["target"],
                type=item["type"],
                confidence=item["confidence"],
                extraction_tool=item["extraction_tool"],
                evidence=[Evidence(**evidence) for evidence in item.get("evidence", [])],
                build_context=item.get("build_context"),
                architecture_context=item.get("architecture_context"),
                index_version=item.get("index_version", INDEX_VERSION),
                metadata=dict(item.get("metadata") or {}),
            )
        return graph
