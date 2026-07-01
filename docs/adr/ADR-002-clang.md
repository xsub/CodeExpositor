# ADR-002: Use Clang/LLVM for semantic C/C++ analysis

Status: Accepted

## Context

Correct C/C++ analysis requires compiler flags, include paths, macros, overload resolution, templates and translation-unit context.

## Decision

Use Clang/LLVM LibTooling as the semantic source of truth for C/C++ analysis.

## Consequences

The system can perform build-aware analysis. Integration cost is higher than syntax-only tools, but semantic quality is substantially better.
