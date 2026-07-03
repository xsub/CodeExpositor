# Code Expositor MVP Implementation Plan

This document maps the roadmap milestones to the first executable core.

The first implementation is intentionally small, deterministic and corpus-driven. It validates the canonical graph shape, query API, CLI surface, storage boundary and visualization/reporting flow before adding heavier semantic tooling.

## Delivery Contract

The MVP loop delivers each layer as a public Python API plus CLI command:

1. package skeleton
2. repository intake
3. outline index
4. symbol index
5. include graph
6. build context loader
7. README/docs snippet index
8. direct-call graph baseline
9. architecture slice classifier
10. SQLite graph store
11. query API
12. DOT and SVG exporters
13. static HTML report
14. evidence-bound explanation payloads
15. evidence-bound case-study workflows
16. canonical graph validation gate
17. local milestone doctor

## Adapter Boundary

The core graph model is independent of extraction tools.

Early extractors may use deterministic built-in parsing for tiny C and C++ corpora. The optional tree-sitter, Universal Ctags and Clang adapters must emit the same canonical node, edge and evidence structures instead of changing the internal schema.

tree-sitter is exposed through `outline --source auto|regex|tree-sitter` and graph-building commands through `--outline-source`. If tree-sitter runtime packages are unavailable, `auto` falls back to the deterministic regex outline and reports diagnostics.

Universal Ctags is an optional symbol adapter, not a hard runtime dependency for the first loop. If the local system only provides BSD / Apple `ctags` without a stable machine-readable output, the deterministic built-in symbol fallback should be preferred. The CLI exposes this boundary with `symbols --source auto|outline|ctags`; graph-building commands can opt into the same choice with `--symbol-source`.

## First Validation Target

The first validation target is `corpus/tiny-c/` and `corpus/tiny-cpp/`.

FFmpeg remains the first large validation target, but FFmpeg-specific case studies should only be added after the core can scan, index, query, store and report on tiny corpora.

## Milestone Acceptance

A milestone is considered delivered when:

- it produces deterministic structured output
- graph edges include confidence, extraction tool and evidence location where available
- graph validation reports zero schema/integrity errors
- the CLI can expose the output
- tests cover the tiny corpus behavior
- reports and exporters consume the canonical graph, not extractor-specific state

## Non Goals For The First Loop

The first loop does not implement:

- PyQt5
- LLM calls
- whole-FFmpeg semantic coverage
- complete indirect-call resolution
- runtime tracing
- distributed graph processing

The explanation layer produces evidence-bound payloads and deterministic prose only. External LLM integration can be added after query results and evidence packaging stabilize.

## Semantic Overlay

Clang AST extraction can be enabled as an optional semantic overlay for graph-building commands. Semantic facts are merged into the canonical graph with their own `extraction_tool` provenance, confidence and evidence locations.

The fallback graph remains available without Clang. When semantic extraction is enabled, it validates or augments the graph; it does not replace the canonical schema.

The semantic spike is validated on both tiny C and tiny C++ corpora. The C++ fixture includes a build context and verifies extraction of a method-to-function call before larger FFmpeg translation units are attempted.

For Make-based projects such as FFmpeg, `expositor build-context` can capture selected compile commands from `make -n V=1 TARGET` and write a minimal `compile_commands.json`. This is a build-system adapter: it records the compiler command emitted by Make and does not invent flags. The selected FFmpeg MPEG-4 translation unit can then be parsed with `graph --semantic --semantic-limit 1`.

## Visualization Adapter

DOT export is the canonical visualization handoff. SVG output can be rendered by the dependency-free internal renderer or, when available, by Graphviz through `export svg --renderer auto|internal|graphviz`. Graphviz remains an adapter over canonical graph DOT, not an internal graph representation.

## SQLite Storage

The SQLite store persists canonical nodes, edges, evidence and an adjacency projection. The `adjacency` table is derived from `edges`; it supports traversal-oriented queries without becoming a separate graph schema or source of truth.

`expositor store-info` inspects a saved graph store and verifies that incoming and outgoing adjacency row counts match canonical edge counts.

## Local Doctor

`expositor doctor` audits local milestone readiness: required repository layout, tiny corpora, tiny graph validation, tiny SQLite persistence and adjacency projection, tiny MPEG-4 implementation-candidate evidence plus a static path, tiny DOT/SVG/HTML rendering, optional adapter availability and FFmpeg checkout detection. Pending FFmpeg validation is reported separately from local tiny-corpus correctness.

When `--ffmpeg-root` is supplied, doctor performs a lightweight FFmpeg readiness check before deeper semantic validation: it confirms the recognizable FFmpeg layout, scans repository intake metadata, verifies `libavcodec` / `libavformat`, and reports MPEG-4 path candidates under `libavcodec`.

Doctor also reports FFmpeg build-context readiness as a separate gate. This gate only passes when `compile_commands.json` is present, contains translation units, and includes at least one MPEG-4 `libavcodec` translation unit. This keeps graph/case-study validation distinct from build-aware Clang semantic validation.

The text format is intentionally not a raw metadata dump. It surfaces only the details needed for the next operator decision: tiny implementation candidates, diagram counts, SQLite adjacency counts and FFmpeg MPEG-4 candidate paths.

## Documentation Signals

Top-down explanations may consume deterministic README/docs snippets as context signals. Documentation snippets must include file and line evidence, and they must not create architecture, dependency or call-path facts by themselves.

## Case Study Boundary

Case studies, including MPEG-4 / FFmpeg analysis, must consume the canonical graph through the query API.

They may define search terms, report shape and follow-up questions, but they must not implement separate repository parsing, graph traversal or semantic analysis.

Case-study output should distinguish implementation candidates from broad name/path matches. A candidate must cite the selected graph node, role, file path, line and match basis so declarations, definitions and unresolved symbols are not collapsed into one claim. Public API candidates should be surfaced separately because they answer a different question than implementation location.

Static HTML reports may embed case-study slices, but those slices must be rendered from the same case-study API and canonical graph evidence used by the CLI.
