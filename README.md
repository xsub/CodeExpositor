# Code Expositor

**Code Expositor** is a build-aware, architecture-aware source-code understanding system for large C/C++ codebases.

Its purpose is to extract a deterministic multi-layer code knowledge graph from a repository and use AI only as an explanation layer over verified graph evidence.

The first validation target is **FFmpeg**.

## What the project explains

Code Expositor is intended to explain:

- repository structure
- modules and libraries
- directory responsibilities
- public APIs
- important data structures
- include and module dependencies
- function-level relationships
- selected call paths
- architecture-specific code paths
- build/configuration-dependent code selection

This is not primarily a call graph visualizer. A call graph is one layer inside a broader code knowledge graph.

## Core principle

The graph is the source of truth. AI explains evidence; AI does not invent architecture.

## Initial documentation

- [Architecture Specification v0.1](docs/architecture-spec-v0.1.md)
- [MVP Roadmap](docs/roadmap-mvp.md)
- [Canonical Graph Model](docs/graph-model.md)
- [AI Evidence Contract](docs/ai-contract.md)

## Design direction

External tools may be used as importers, validators or renderers, but the project owns its internal graph schema.

Likely foundation:

- Clang/LLVM LibTooling for build-aware C/C++ semantic analysis
- tree-sitter for fast repository outline
- Universal Ctags as an early symbol baseline
- SQLite for metadata and evidence storage
- adjacency tables / CSR-style arrays for traversal
- Graphviz / Cytoscape.js for visualization
- optional CodeQL comparison as an oracle, not as the core
