"""Build-aware semantic spike layer."""

from expositor.semantic.api import ClangSemanticIndex, SemanticCall, SemanticFunction, build_clang_semantic_index

__all__ = [
    "ClangSemanticIndex",
    "SemanticCall",
    "SemanticFunction",
    "build_clang_semantic_index",
]
