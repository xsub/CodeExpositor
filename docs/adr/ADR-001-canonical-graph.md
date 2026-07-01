# ADR-001: Use a canonical internal graph model

Status: Accepted

## Context

The project integrates multiple external tools: Clang, tree-sitter, ctags, CodeQL, Doxygen, Graphviz and possibly graph databases. Each has its own model.

## Decision

Code Expositor will define and own a canonical internal graph model.

External tools are adapters, importers, validators or exporters.

## Consequences

The architecture remains independent from CodeQL, Doxygen, Sourcetrail, Neo4j or GraphScope. Importers may evolve without changing the core query model.
