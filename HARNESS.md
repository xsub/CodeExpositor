# Code Expositor - AI Development Harness

You are working on Code Expositor.

Code Expositor is a build-aware, architecture-aware source-code understanding system for large C/C++ codebases.

The first validation target is FFmpeg.

## Core Rule

The graph is the source of truth.

AI explains extracted evidence.
AI must never invent architecture, execution paths, modules, functions or dependencies.

## Product Goal

Build a deterministic multi-layer code knowledge graph from source repositories and expose it through:

- CLI
- Query API
- Reports
- Visualizations
- Evidence-bound AI explanations

## Project Naming

Project:
Code Expositor

Python package:
expositor

Core engine:
Expositor Core

Never use legacy names such as:

- Code Atlas
- Atlas
- atlas

## Architectural Principles

The canonical graph is the product.

Everything else consumes the graph.

External tools are adapters, validators or renderers only.

Never make any of the following the internal architecture:

- CodeQL
- Doxygen
- Sourcetrail
- Neo4j
- GraphScope
- Graphviz
- Cytoscape.js
- PyQt5

Code Expositor owns its internal graph schema.

## Preferred Technology Stack

MVP direction:

- Python
- expositor/
- CLI-first
- SQLite
- tree-sitter for outline
- Universal Ctags for early symbols
- Clang/LLVM for semantic analysis
- Graphviz
- SVG
- Static HTML reports

PyQt5 comes later.

## Architectural Layers

Repository Intake

->

Outline Index

->

Symbol Index

->

Include Graph

->

Build Context

->

Semantic Index

->

Call Graph

->

Architecture Slice

->

Canonical Graph Store

->

Query API

->

Explanation Layer

->

Visualization Clients

Every layer should have a clean public API.

## UI Architecture

All user interfaces are clients of Expositor Core.

Desktop applications,
browser applications,
IDE plugins

must never implement:

- graph construction
- graph traversal
- repository parsing
- semantic analysis

These belong exclusively to Expositor Core.

## Visualization Strategy

Visualization should appear early.

The first outputs should be:

- Graphviz
- SVG
- Static HTML

Only later:

- Cytoscape.js
- PyQt5

PyQt5 is NOT part of the MVP.

PyQt5 should be introduced only after:

- canonical graph schema
- repository intake
- outline index
- semantic index
- SQLite graph store
- Query API
- HTML reports
- Graphviz export

have stabilized.

## AI Contract

LLM input must consist of:

- graph nodes
- graph edges
- evidence
- file locations
- symbol locations
- confidence labels

LLM must distinguish:

- confirmed
- likely
- possible
- unresolved

Never infer runtime behaviour from static analysis alone.

Never hallucinate functions or architecture.

## Initial CLI

expositor scan

expositor outline

expositor symbols

expositor includes

expositor callers

expositor callees

expositor paths-to

expositor report

expositor export dot

expositor export svg

## Documentation First

Before implementing large features, update documentation.

Important documents:

docs/architecture-spec-v0.1.md

docs/roadmap-mvp.md

docs/graph-model.md

docs/ai-contract.md

docs/adr/

Architecture evolves through ADRs.

## Commit Style

Use conventional commits.

Examples:

docs: define visualization architecture

docs: add repository intake design

build: initialize Python package

feat: add repository scan command

feat: add SQLite graph schema

feat: implement outline index

test: add tiny C corpus

## Current Development Priority

Do NOT start with:

- PyQt5
- LLM integration
- FFmpeg call graph

Start with:

1. package skeleton

2. repository intake

3. outline index

4. symbol index

5. include graph

6. SQLite graph store

7. query API

8. Graphviz

9. Static HTML reports

10. Clang semantic spike

11. Call graph

12. FFmpeg case study

## Quality Requirements

Every extractor must produce deterministic structured output.

Every graph edge should eventually contain:

- source node
- target node
- edge type
- confidence
- extraction tool
- evidence location
- build context

## MVP Non Goals

MVP does not require:

- perfect indirect-call resolution

- runtime tracing

- distributed graph processing

- complete FFmpeg coverage

- perfect template analysis

- polished desktop UI

## Validation Projects

Use:

corpus/tiny-c/

corpus/tiny-cpp/

FFmpeg

Tiny projects validate correctness.

FFmpeg demonstrates value.
