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
- [MVP Implementation Plan](docs/mvp-implementation-plan.md)
- [MVP Status](docs/mvp-status.md)

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

## Current executable MVP

The repository now includes a small Python package named `expositor`, tiny C/C++ validation corpora and a CLI-first graph pipeline.
Top-down explanations combine graph evidence with README/docs snippets as context signals.

Example commands:

```bash
expositor schema
expositor scan corpus/tiny-c
expositor outline corpus/tiny-c --source auto
expositor symbols corpus/tiny-c --source auto --outline-source auto
expositor includes corpus/tiny-c
expositor semantic corpus/tiny-c --limit 2
expositor semantic corpus/tiny-cpp --limit 1
expositor graph corpus/tiny-c --outline-source auto --semantic --semantic-limit 2
expositor graph corpus/tiny-c --db graph.sqlite
expositor store-info graph.sqlite
expositor graph corpus/tiny-cpp --semantic --semantic-limit 1
expositor validate corpus/tiny-c --outline-source auto
expositor validate corpus/tiny-cpp --semantic --semantic-limit 1
expositor doctor .
expositor doctor . --ffmpeg-root /path/to/ffmpeg
expositor explain repository corpus/tiny-c
expositor explain repository corpus/tiny-c --format payload
expositor explain function corpus/tiny-c --value decode_frame --format payload
expositor explain path corpus/tiny-c --value decode_mpeg4_packet --format payload
expositor query symbols-in corpus/tiny-c --value src
expositor query architecture-slice corpus/tiny-c --value x86
expositor callers decode_mpeg4_packet corpus/tiny-c
expositor public-api include corpus/tiny-c
expositor includes-of src/decoder.c corpus/tiny-c
expositor dependents-of include/codec.h corpus/tiny-c
expositor paths-to decode_mpeg4_packet corpus/tiny-c
expositor paths-from main decode_mpeg4_packet corpus/tiny-c
expositor why-reachable decode_mpeg4_packet corpus/tiny-c
expositor evidence-for src/decoder.c corpus/tiny-c
expositor case-study mpeg4 corpus/tiny-c
expositor export dot corpus/tiny-c --graph includes
expositor export svg corpus/tiny-c --graph calls --renderer auto --output calls.svg
expositor report corpus/tiny-c --html --output report.html
```

From an uninstalled checkout, the same commands can be run as `python3 -m expositor.cli ...`.

`expositor doctor` is the local milestone gate. In text mode it reports the pass/warn/pending counts plus the highest-signal evidence for delivered gates: tiny MPEG-4 implementation candidates, generated SVG/HTML diagram counts, SQLite adjacency counts and, when `--ffmpeg-root` is provided, FFmpeg MPEG-4 readiness candidates under `libavcodec` plus build-context readiness for selected Clang semantic validation.

For larger validation, keep an FFmpeg checkout outside tracked source files, for example `.external/ffmpeg`, and run the same CLI pipeline with `--db` so validation, reports, explanations and case studies all consume the same persisted canonical graph.

Checked-in FFmpeg example outputs are available under [examples/ffmpeg](examples/ffmpeg/). They include a sample `doctor` report, a captured build context for `libavcodec/mpeg4videodec.c`, and a condensed MPEG-4 case-study JSON result.

When FFmpeg has been configured, a selected translation unit can be captured from Make without external interception tools:

```bash
python3 -m expositor.cli build-context .external/ffmpeg \
  --make-target libavcodec/mpeg4videodec.o \
  --write-compile-commands compile_commands.json
python3 -m expositor.cli graph .external/ffmpeg --semantic --semantic-limit 1
```

The same core can be used as a Python library:

```python
from expositor import QueryEngine, build_canonical_graph, graph_schema

schema = graph_schema()
graph = build_canonical_graph("corpus/tiny-c")
query = QueryEngine(graph)
```

Run tests with:

```bash
python3 -m unittest discover -v
```
