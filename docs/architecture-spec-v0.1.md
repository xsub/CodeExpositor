# Code Expositor — Architecture Specification v0.1

## Product Definition

Code Expositor is a build-aware, architecture-aware source-code understanding system for large C/C++ codebases.

Its purpose is to extract a deterministic multi-layer code knowledge graph from a repository and use AI only as an explanation layer over verified graph evidence.

The first validation target is FFmpeg.

## Design Principles

1. The graph is the source of truth.
2. AI explains evidence; AI does not invent architecture.
3. The internal graph schema is canonical and independent of external tools.
4. External tools are adapters, importers, validators or renderers.
5. Build configuration is a first-class part of the graph.
6. Architecture-specific code is a first-class part of the graph.
7. Static analysis must expose uncertainty instead of hiding it.
8. MVP must be useful before perfect call graph precision exists.

## MVP Scope

MVP target: explain FFmpeg at repository, module, file, symbol and selected call-path level.

MVP must answer:

- What are FFmpeg's main libraries?
- What does each major directory do?
- Which files define MPEG-4 decoding?
- Which symbols are defined in a selected module?
- Which files include or depend on each other?
- Which public APIs appear to lead toward decoder execution?
- Which functions call or reference selected decoder routines?
- What possible static paths lead to a selected function?
- Which source files are architecture-specific?

MVP does not need to solve full runtime behavior, perfect indirect-call resolution, full UI polish, distributed graph processing or whole-program proof of execution.

## System Architecture

```text
Repository
  -> Repository Intake
  -> Outline Index
  -> Symbol Index
  -> Include / Module Graph
  -> Build-Aware Semantic Index
  -> Call Graph Layer
  -> Architecture / Config Slice
  -> Canonical Code Knowledge Graph
  -> Query Engine
  -> AI Explanation Layer
  -> UI / Reports / Exports
```

## Core Components

### Repository Intake

Scans a repository, detects languages and build files, inventories files and directories, and produces a repository manifest.

### Outline Index

Uses tree-sitter, ripgrep and optionally Universal Ctags to extract rough structure quickly. This layer is useful for navigation and top-down summaries, but is not semantically authoritative.

### Symbol Index

Builds a symbol database. Universal Ctags may be used initially; Clang becomes the semantic source of truth later.

### Include and Module Dependency Graph

Extracts include relationships, file dependencies, directory dependencies and inferred module dependencies.

### Build-Aware Semantic Index

Uses compile_commands.json and Clang/LLVM LibTooling to parse real translation units with compiler flags, include paths and macro definitions.

### Call Graph Layer

Extracts direct calls, unresolved calls, possible indirect calls and callback references where possible. Every edge carries confidence.

### Architecture / Config Slice

Associates graph facts with architecture, build target, compiler flags and feature flags. Detects generic fallback and architecture-specific code.

### Canonical Graph Store

The project owns its graph schema. MVP storage uses SQLite for metadata and evidence, with adjacency tables for traversal. Graph databases are optional exports, not the core.

## Reuse Policy

Safe foundation:

- Clang/LLVM LibTooling
- compile_commands.json
- tree-sitter for outline only
- SQLite
- Graphviz export
- Cytoscape.js UI

Adapter only:

- Universal Ctags
- Bear
- Doxygen
- GNU Global
- cscope
- cflow

Oracle / validator only:

- CodeQL

Reference only:

- Sourcetrail
- Sourcegraph concepts
- GraphScope architecture
- Neo4j graph exploration
