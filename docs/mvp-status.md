# Code Expositor MVP Status

This status tracks executable milestone coverage against `HARNESS.md` and the MVP roadmap.

## Current Validation

Tiny corpora are the active correctness gate:

```bash
python3 -m unittest discover -v
expositor schema
expositor validate corpus/tiny-c --format json
expositor validate corpus/tiny-cpp --semantic --semantic-limit 1 --format json
expositor doctor .
```

The current tiny C graph and tiny C++ semantic graph validate with zero schema or integrity errors and zero warnings.

A shallow FFmpeg validation checkout is also available in this workspace under `.external/ffmpeg` (ignored by git). The latest large validation run used FFmpeg commit `1836ef9` from 2026-07-02.

```bash
expositor doctor . --ffmpeg-root .external/ffmpeg
(cd .external/ffmpeg && ./configure --cc=clang --disable-everything --disable-programs --disable-doc --disable-autodetect --disable-x86asm --enable-avcodec --enable-decoder=mpeg4 --enable-parser=mpeg4video)
expositor build-context .external/ffmpeg --make-target libavcodec/mpeg4videodec.o --write-compile-commands compile_commands.json
expositor graph .external/ffmpeg --outline-source auto --symbol-source auto --db /private/tmp/ffmpeg-expositor.sqlite
expositor graph .external/ffmpeg --outline-source auto --symbol-source auto --semantic --semantic-limit 1 --db /private/tmp/ffmpeg-semantic-expositor.sqlite
expositor validate .external/ffmpeg --db /private/tmp/ffmpeg-expositor.sqlite --format json
expositor validate .external/ffmpeg --db /private/tmp/ffmpeg-semantic-expositor.sqlite --format json
expositor case-study mpeg4 .external/ffmpeg --db /private/tmp/ffmpeg-expositor.sqlite
expositor case-study mpeg4 .external/ffmpeg --db /private/tmp/ffmpeg-semantic-expositor.sqlite
expositor explain repository .external/ffmpeg --db /private/tmp/ffmpeg-expositor.sqlite --format payload
expositor report .external/ffmpeg --db /private/tmp/ffmpeg-expositor.sqlite --html
```

The FFmpeg canonical graph validates with 65,379 nodes, 119,050 edges, zero schema/integrity errors and zero warnings. SQLite storage reports matching incoming and outgoing adjacency counts for all 119,050 canonical edges.

The selected FFmpeg semantic graph validates with 72,748 nodes, 128,155 edges, zero schema/integrity errors and zero warnings. It includes 3,534 Clang definition/declaration edges and 2,296 Clang call edges from `libavcodec/mpeg4videodec.c`.

## Milestone Matrix

| Milestone | Status | Executable surface |
| --- | --- | --- |
| 0. Repository setup | Delivered | `pyproject.toml`, `expositor/`, `docs/`, `docs/adr/`, `corpus/`, `tests/` |
| Canonical schema | Delivered | `expositor schema` |
| Public Python API | Delivered | `import expositor`, `graph_schema()`, `build_canonical_graph()`, `QueryEngine` |
| 1. Repository intake | Delivered | `expositor scan` |
| 2. Outline index | Delivered with optional tree-sitter adapter and regex fallback | `expositor outline --source auto|regex|tree-sitter` |
| 3. Symbol index | Delivered | `expositor symbols --source auto|outline|ctags` |
| 4. Include graph | Delivered | `expositor includes`, canonical `INCLUDES` and `DEPENDS_ON` edges |
| 5. Top-down explanation | Delivered for tiny corpus and FFmpeg payload smoke test | `expositor explain repository` |
| 6. Build context | Delivered, including Make dry-run capture for selected FFmpeg translation units | `expositor build-context`, `compile_commands.json` ingestion, `--make-target` |
| 7. Clang semantic spike | Delivered for tiny C/C++ corpora and selected FFmpeg MPEG-4 translation unit | `expositor semantic`, `graph --semantic` |
| SQLite graph store | Delivered with adjacency projection inspection | `expositor graph --db`, `expositor store-info` |
| 8. Call graph v0.1 | Delivered | `expositor callers`, `callees`, `paths-to` |
| 9. MPEG-4 case study | Workflow delivered and validated on FFmpeg with ranked evidence-bound implementation candidates | `expositor case-study mpeg4` |
| 10. Architecture slice | Delivered | `expositor architecture`, `query architecture-slice` |
| 11. Evidence-bound AI explanation | Delivered without external LLM calls; payload includes nodes, edges, evidence, file locations, symbol locations, confidence and limitations | `expositor explain repository|module|file|function|path|architecture|where --format payload` |
| 12. Minimal reports | Delivered with embedded SVG diagrams and MPEG-4 case-study slice; FFmpeg report smoke test passes | `expositor report --html` |
| Early visualization | Delivered | `export dot`, `export svg --renderer auto|internal|graphviz`, selected path SVG |
| Quality gate | Delivered | `expositor validate` |
| Local milestone audit | Delivered | `expositor doctor`, including canonical schema, SQLite store, tiny exports, HTML report validation and text evidence details |

## Query CLI Coverage

The full Query API is available through `expositor query ...`. Common graph queries also have direct CLI entry points:

- `public-api`
- `includes-of`
- `dependents-of`
- `paths-from`
- `why-reachable`
- `evidence-for`

## Adapter Status

- Universal Ctags: optional adapter implemented. If local `ctags` is BSD / Apple ctags or unavailable, `--source auto` falls back to deterministic outline symbols.
- Graphviz: optional SVG renderer implemented. If `dot` is unavailable, `--renderer auto` falls back to the internal SVG renderer.
- Clang: optional semantic overlay implemented and covered by tiny C and C++ tests when `clang` is available.
- tree-sitter: optional runtime adapter implemented. If tree-sitter packages are unavailable, `--source auto` falls back to deterministic regex outline and reports diagnostics.

## FFmpeg Validation Status

FFmpeg remains the first large validation target. Large-repo scan, canonical graph build, SQLite persistence, validation, static HTML report generation, evidence payload generation and MPEG-4 case study execution have all run against the shallow checkout in `.external/ffmpeg`.

`expositor doctor . --ffmpeg-root .external/ffmpeg` passes the FFmpeg checkout and MPEG-4 readiness gates. The readiness scan finds 33 MPEG-4 path candidates under `libavcodec`.

`doctor` also reports `ffmpeg_build_context` separately from MPEG-4 graph readiness. After FFmpeg configure and Make dry-run capture, this check passes with one MPEG-4 translation unit under `libavcodec`.

The non-semantic MPEG-4 case study finds 82 matching symbols, 116 matching files and 41 public API candidates. The semantic MPEG-4 case study finds 273 matching symbols, 117 matching files and 41 public API candidates. Its top ranked implementation candidates are confirmed definitions in `libavcodec/mpeg4videodec.c`, including `ff_mpeg4_decode_studio` at line 260, `ff_mpeg4_decode_video_packet_header` at line 708 and `mpeg4_decode_block` at line 1381.

The remaining large-repository work is breadth, not the MVP spike: expand from one selected MPEG-4 translation unit to a broader FFmpeg semantic pass once more build targets are captured.
