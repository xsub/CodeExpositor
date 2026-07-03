"""Code Expositor core package."""

from .graph import build_canonical_graph
from .intake import scan_repository
from .model import Confidence, Edge, EdgeType, Evidence, Graph, Node, NodeType, graph_schema
from .queries import QueryEngine
from .validation import ValidationReport, validate_graph

__version__ = "0.1.0"

__all__ = [
    "Confidence",
    "Edge",
    "EdgeType",
    "Evidence",
    "Graph",
    "Node",
    "NodeType",
    "QueryEngine",
    "ValidationReport",
    "__version__",
    "build_canonical_graph",
    "graph_schema",
    "scan_repository",
    "validate_graph",
]
