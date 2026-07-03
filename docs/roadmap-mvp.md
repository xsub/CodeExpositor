# Code Expositor — MVP Roadmap

## Milestone 0 — Repository Setup

Deliverables:

- project repository
- CLI skeleton
- documentation structure
- ADR directory
- sample corpus directory
- test fixture repository

Suggested structure:

```text
code-expositor/
  expositor/
    intake/
    outline/
    symbols/
    graph/
    storage/
    queries/
    explain/
    exporters/
  docs/
    adr/
  corpus/
    tiny-c/
    tiny-cpp/
  tests/
```

## Milestone 1 — Repository Intake

Goal: scan a repository and produce structured inventory.

Command:

```bash
expositor scan /path/to/repo
```

Outputs: files, directories, language counts, top-level modules, build files and generated-file candidates.

## Milestone 2 — Outline Index

Goal: extract rough code structure.

Use tree-sitter and ripgrep fallback.

Extract functions, structs, enums, macros, comments and file-level summary signals.

## Milestone 3 — Symbol Index

Goal: build first symbol database.

Use Universal Ctags initially, later Clang AST.

Extract symbol name, kind, file, line, scope and declaration/definition distinction where available.

## Milestone 4 — Include Graph

Goal: build file and directory dependency graph.

Extract local includes, system includes, file-to-file edges, directory-to-directory edges and inferred module dependencies.

## Milestone 5 — FFmpeg Top-Down Explanation

Goal: generate useful architecture explanation without call graph.

Inputs: repository inventory, outline index, symbols, include graph and README/docs snippets.

Expected result: top-level architecture summary, module responsibilities, important files, important symbols, dependency summary and uncertainty section.

## Milestone 6 — Build Context

Goal: support build-aware analysis.

Load compile_commands.json, map source files to translation units, extract compiler flags, include paths, macro definitions and target architecture where possible.

## Milestone 7 — Clang Semantic Index Spike

Goal: parse selected translation units with Clang.

Start with tiny C and C++ projects, then selected FFmpeg files.

Extract functions, declarations, definitions, direct call expressions and callsite locations.

## Milestone 8 — Call Graph v0.1

Goal: build direct-call graph.

Commands:

```bash
expositor callers function_name
expositor callees function_name
expositor paths-to function_name --max-depth 8
```

Edge types: CALLS, MAY_CALL, UNRESOLVED.

## Milestone 9 — FFmpeg MPEG-4 Case Study

Goal: demonstrate real value.

Questions:

- Where is MPEG-4 decoding implemented?
- Which files contain MPEG-4 decoder logic?
- Which public APIs may lead toward this code?
- Which functions directly call selected MPEG-4 decode functions?
- What possible path reaches selected function?

## Milestone 10 — Architecture Slice v0.1

Goal: recognize architecture-specific code.

Implement directory classification for x86, arm, aarch64, riscv and similar architecture directories. Add architecture nodes and ARCH_SPECIFIC edges.

## Milestone 11 — Evidence-Bound AI Explanation

Goal: add LLM explanation over graph evidence.

LLM input must be structured graph/evidence JSON, not raw repository dump.

## Milestone 12 — Minimal Reports

Goal: produce consumable output.

MVP output:

```bash
expositor report /path/to/repo --html
```

Report sections: repository overview, module map, dependency graph, symbol browser, selected call paths, architecture-specific files and AI summaries with evidence.


## Early Visualization Strategy

Visualization should appear as early as possible, but not as a GUI-first effort.

The primary objective is to validate the correctness of the extracted graph and the usefulness of the generated explanations before investing in desktop or web interfaces.

The first visualization layer should be generated directly from the canonical graph and query engine.

Initial visualization outputs:

- Graphviz DOT export
- SVG generation
- static HTML reports
- module dependency diagrams
- include dependency graphs
- selected call-path diagrams
- architecture-specific slices

Example commands:

```bash
expositor export dot --graph includes
expositor export svg --graph includes
expositor report --html
expositor callers function_name
expositor paths-to function_name --format svg
```

This allows immediate validation of graph extraction without introducing GUI complexity.

## Desktop UI Strategy

PyQt5 is intentionally **not** part of the initial MVP.

The desktop application should only be introduced after the core engine becomes stable.

Required prerequisites:

- canonical graph schema
- repository intake
- outline index
- semantic index
- SQLite graph store
- query engine
- Graphviz/DOT export
- HTML report generation
- evidence-bound explanation pipeline

At this stage PyQt5 becomes a frontend only.

The desktop application must never own graph extraction, indexing or analysis logic.

Its responsibilities should be limited to:

- repository browser
- graph explorer
- function viewer
- query execution
- SVG viewer
- AI explanation panel

All graph extraction, indexing and analysis must remain inside the Expositor core libraries.

## Recommended UI Evolution

```text
CLI
    ↓
Graphviz / SVG
    ↓
Static HTML reports
    ↓
Interactive browser visualization (Cytoscape.js)
    ↓
PyQt5 desktop application
    ↓
Optional IDE extensions
```

**Guiding principle**

The visualization layer is replaceable.

The graph engine is not.
