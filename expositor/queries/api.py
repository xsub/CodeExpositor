"""Structured query API over the canonical graph."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any

from expositor.model import Edge, EdgeType, Graph, Node, NodeType


CALL_EDGE_TYPES = {EdgeType.CALLS.value, EdgeType.MAY_CALL.value, EdgeType.UNRESOLVED.value}
SYMBOL_NODE_TYPES = {
    NodeType.FUNCTION.value,
    NodeType.METHOD.value,
    NodeType.MACRO.value,
    NodeType.STRUCT.value,
    NodeType.CLASS.value,
    NodeType.ENUM.value,
    NodeType.TYPEDEF.value,
    NodeType.SYMBOL.value,
}


@dataclass
class QueryEngine:
    graph: Graph

    def repo_summary(self) -> dict[str, Any]:
        nodes_by_type = Counter(node.type for node in self.graph.nodes.values())
        edges_by_type = Counter(edge.type for edge in self.graph.edges.values())
        repos = self.graph.nodes_of_type(NodeType.REPOSITORY)
        repo = repos[0] if repos else None
        return {
            "repository": repo.to_dict() if repo else None,
            "node_counts": dict(sorted(nodes_by_type.items())),
            "edge_counts": dict(sorted(edges_by_type.items())),
        }

    def module_summary(self, path: str) -> dict[str, Any]:
        nodes = [
            node
            for node in self.graph.nodes.values()
            if node.path and (node.path == path or node.path.startswith(f"{path.rstrip('/')}/"))
        ]
        module_nodes = [
            node
            for node in self.graph.nodes_of_type(NodeType.MODULE)
            if node.path == path or node.label == path
        ]
        module_ids = {node.id for node in module_nodes}
        outgoing_dependencies = [
            self._edge_with_nodes(edge)
            for edge in self.graph.edges.values()
            if edge.source in module_ids and edge.type == EdgeType.DEPENDS_ON.value
        ]
        incoming_dependencies = [
            self._edge_with_nodes(edge)
            for edge in self.graph.edges.values()
            if edge.target in module_ids and edge.type == EdgeType.DEPENDS_ON.value
        ]
        return {
            "module": path,
            "node_counts": dict(sorted(Counter(node.type for node in nodes).items())),
            "files": [
                node.to_dict()
                for node in sorted(
                    nodes,
                    key=lambda item: (item.path or "", item.label),
                )
                if node.type in {NodeType.FILE.value, NodeType.SOURCE_FILE.value, NodeType.HEADER_FILE.value}
            ],
            "symbols": [
                node.to_dict()
                for node in sorted(
                    nodes,
                    key=lambda item: (item.path or "", item.metadata.get("line", 0), item.label),
                )
                if node.type in SYMBOL_NODE_TYPES
            ],
            "outgoing_dependencies": outgoing_dependencies,
            "incoming_dependencies": incoming_dependencies,
        }

    def file_summary(self, path: str) -> dict[str, Any]:
        file_node = self._node_by_path(path)
        if not file_node:
            return {"file": path, "found": False}
        outgoing = self._edges_from(file_node.id)
        incoming = self._edges_to(file_node.id)
        return {
            "file": file_node.to_dict(),
            "found": True,
            "outgoing_edges": [edge.to_dict() for edge in outgoing],
            "incoming_edges": [edge.to_dict() for edge in incoming],
        }

    def symbols_in(self, path: str) -> dict[str, Any]:
        file_nodes = [
            node
            for node in self.graph.nodes.values()
            if node.path and (node.path == path or node.path.startswith(f"{path.rstrip('/')}/"))
        ]
        file_ids = {node.id for node in file_nodes}
        symbol_edges = [
            edge
            for edge in self.graph.edges.values()
            if edge.source in file_ids and edge.type in {EdgeType.DECLARES.value, EdgeType.DEFINES.value}
        ]
        symbol_ids = {edge.target for edge in symbol_edges}
        symbols = [self.graph.nodes[node_id].to_dict() for node_id in sorted(symbol_ids)]
        return {"path": path, "symbols": symbols}

    def public_api(self, module: str) -> dict[str, Any]:
        apis = [
            node
            for node in self.graph.nodes_of_type(NodeType.PUBLIC_API)
            if node.path and (node.path == module or node.path.startswith(f"{module.rstrip('/')}/"))
        ]
        return {"module": module, "public_api": [node.to_dict() for node in sorted(apis, key=lambda item: (item.path or "", item.label))]}

    def includes_of(self, file: str) -> dict[str, Any]:
        node = self._node_by_path(file)
        if not node:
            return {"file": file, "includes": []}
        edges = [edge for edge in self._edges_from(node.id) if edge.type == EdgeType.INCLUDES.value]
        return {"file": file, "includes": [self._edge_with_nodes(edge) for edge in edges]}

    def dependents_of(self, path: str) -> dict[str, Any]:
        node = self._node_by_path(path)
        if not node:
            return {"path": path, "dependents": []}
        edges = [
            edge
            for edge in self._edges_to(node.id)
            if edge.type in {EdgeType.INCLUDES.value, EdgeType.DEPENDS_ON.value}
        ]
        return {"path": path, "dependents": [self._edge_with_nodes(edge) for edge in edges]}

    def callers_of(self, function: str) -> dict[str, Any]:
        targets = self._function_nodes(function)
        target_ids = {node.id for node in targets}
        edges = [
            edge
            for edge in self.graph.edges.values()
            if edge.target in target_ids and edge.type in CALL_EDGE_TYPES
        ]
        return {"function": function, "callers": [self._edge_with_nodes(edge) for edge in edges]}

    def callees_of(self, function: str) -> dict[str, Any]:
        callers = self._function_nodes(function)
        caller_ids = {node.id for node in callers}
        edges = [
            edge
            for edge in self.graph.edges.values()
            if edge.source in caller_ids and edge.type in CALL_EDGE_TYPES
        ]
        return {"function": function, "callees": [self._edge_with_nodes(edge) for edge in edges]}

    def paths_to(self, function: str, max_depth: int = 8) -> dict[str, Any]:
        targets = self._function_nodes(function)
        reverse = self._reverse_call_adjacency()
        paths: list[list[dict[str, Any]]] = []
        for target in targets:
            queue: deque[tuple[str, list[str]]] = deque([(target.id, [target.id])])
            while queue:
                node_id, path = queue.popleft()
                if len(path) > max_depth + 1:
                    continue
                parents = reverse.get(node_id, [])
                if not parents and len(path) > 1:
                    paths.append([self.graph.nodes[item].to_dict() for item in reversed(path)])
                for parent, _edge in parents:
                    if parent in path:
                        continue
                    next_path = path + [parent]
                    if len(next_path) > max_depth + 1:
                        paths.append([self.graph.nodes[item].to_dict() for item in reversed(next_path)])
                    else:
                        queue.append((parent, next_path))
        paths.sort(key=lambda item: [node["label"] for node in item])
        return {"function": function, "max_depth": max_depth, "paths": paths}

    def paths_from(self, entrypoint: str, target: str, max_depth: int = 8) -> dict[str, Any]:
        starts = self._function_nodes(entrypoint)
        targets = {node.id for node in self._function_nodes(target)}
        forward = self._forward_call_adjacency()
        paths: list[list[dict[str, Any]]] = []
        for start in starts:
            queue: deque[tuple[str, list[str]]] = deque([(start.id, [start.id])])
            while queue:
                node_id, path = queue.popleft()
                if node_id in targets:
                    paths.append([self.graph.nodes[item].to_dict() for item in path])
                    continue
                if len(path) > max_depth:
                    continue
                for child, _edge in forward.get(node_id, []):
                    if child in path:
                        continue
                    queue.append((child, path + [child]))
        paths.sort(key=lambda item: [node["label"] for node in item])
        return {
            "entrypoint": entrypoint,
            "target": target,
            "max_depth": max_depth,
            "paths": paths,
        }

    def architecture_slice(self, arch: str) -> dict[str, Any]:
        arch_nodes = [
            node
            for node in self.graph.nodes_of_type(NodeType.ARCHITECTURE)
            if node.label == arch
        ]
        arch_ids = {node.id for node in arch_nodes}
        edges = [
            edge
            for edge in self.graph.edges.values()
            if edge.target in arch_ids and edge.type == EdgeType.ARCH_SPECIFIC.value
        ]
        return {"architecture": arch, "files": [self._edge_with_nodes(edge) for edge in edges]}

    def why_reachable(self, function: str) -> dict[str, Any]:
        return {
            "function": function,
            "paths": self.paths_to(function, max_depth=8)["paths"],
            "callers": self.callers_of(function)["callers"],
        }

    def evidence_for(self, node_or_edge: str) -> dict[str, Any]:
        node = self.graph.nodes.get(node_or_edge) or self._node_by_path(node_or_edge) or self._node_by_label(node_or_edge)
        if node:
            related_edges = [
                edge for edge in self.graph.edges.values() if edge.source == node.id or edge.target == node.id
            ]
            return {
                "target": node.to_dict(),
                "related_edges": [edge.to_dict() for edge in sorted(related_edges, key=lambda item: item.id)],
            }
        edge = self.graph.edges.get(node_or_edge)
        if edge:
            return {"target": edge.to_dict(), "evidence": [item.to_dict() for item in edge.evidence]}
        return {"target": node_or_edge, "evidence": []}

    def _node_by_path(self, path: str) -> Node | None:
        for node in self.graph.nodes.values():
            if node.path == path:
                return node
        return None

    def _node_by_label(self, label: str) -> Node | None:
        for node in self.graph.nodes.values():
            if node.label == label:
                return node
        return None

    def _function_nodes(self, function: str) -> list[Node]:
        return [
            node
            for node in self.graph.nodes.values()
            if node.type in {NodeType.FUNCTION.value, NodeType.METHOD.value}
            and (node.label == function or node.label.endswith(f"::{function}"))
        ]

    def _edges_from(self, node_id: str) -> list[Edge]:
        return [edge for edge in self.graph.edges.values() if edge.source == node_id]

    def _edges_to(self, node_id: str) -> list[Edge]:
        return [edge for edge in self.graph.edges.values() if edge.target == node_id]

    def _edge_with_nodes(self, edge: Edge) -> dict[str, Any]:
        return {
            "edge": edge.to_dict(),
            "source": self.graph.nodes[edge.source].to_dict(),
            "target": self.graph.nodes[edge.target].to_dict(),
        }

    def _forward_call_adjacency(self) -> dict[str, list[tuple[str, Edge]]]:
        adjacency: dict[str, list[tuple[str, Edge]]] = defaultdict(list)
        for edge in self.graph.edges.values():
            if edge.type in CALL_EDGE_TYPES:
                adjacency[edge.source].append((edge.target, edge))
        return adjacency

    def _reverse_call_adjacency(self) -> dict[str, list[tuple[str, Edge]]]:
        adjacency: dict[str, list[tuple[str, Edge]]] = defaultdict(list)
        for edge in self.graph.edges.values():
            if edge.type in CALL_EDGE_TYPES:
                adjacency[edge.target].append((edge.source, edge))
        return adjacency


def query_engine(graph: Graph) -> QueryEngine:
    return QueryEngine(graph)
