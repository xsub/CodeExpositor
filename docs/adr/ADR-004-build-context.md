# ADR-004: Use compile_commands.json as build context boundary

Status: Accepted

## Context

Static C/C++ analysis without real build flags is unreliable. Include paths, macros and compiler target affect what code exists.

## Decision

Use compile_commands.json as the primary build context boundary.

## Consequences

CMake projects are easy to support. Other build systems may require Bear or similar capture tools. Build configuration becomes a first-class graph entity.
