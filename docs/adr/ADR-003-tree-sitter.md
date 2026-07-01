# ADR-003: Use tree-sitter for fast outline, not semantic truth

Status: Accepted

## Context

tree-sitter is fast and practical for extracting repository outline, but it does not model full C/C++ semantics.

## Decision

Use tree-sitter for fast repository outline, structural indexing and early summaries. Do not use it as the authoritative call graph or symbol resolver.

## Consequences

The MVP can produce useful top-down explanations early while keeping the semantic path open for Clang.
