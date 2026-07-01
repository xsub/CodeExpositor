# ADR-006: Use SQLite plus adjacency tables for MVP storage

Status: Accepted

## Context

Graph databases are useful but would add operational and architectural weight to MVP. The project needs inspectable, portable storage.

## Decision

Use SQLite for metadata, nodes, edges and evidence. Use adjacency tables first, with a migration path toward CSR/mmap arrays for traversal speed.

## Consequences

The MVP stays simple and portable. Neo4j, GraphScope and Graphviz remain export targets rather than core dependencies.
