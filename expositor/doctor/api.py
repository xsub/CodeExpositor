"""Local doctor checks for Code Expositor milestones."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
import tempfile
from typing import Any

from expositor.build_context import load_build_context
from expositor.case_studies import run_mpeg4_case_study
from expositor.exporters import graph_to_dot, graph_to_svg, graphviz_available
from expositor.graph import build_canonical_graph
from expositor.intake import scan_repository
from expositor.model import graph_schema
from expositor.outline import tree_sitter_available
from expositor.report import render_html_report
from expositor.semantic import build_clang_semantic_index
from expositor.storage import save_graph, storage_info
from expositor.symbols.ctags import universal_ctags_available
from expositor.validation import validate_graph


PASS = "pass"
WARN = "warn"
FAIL = "fail"
PENDING = "pending"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    checks: list[DoctorCheck]

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        return {
            "ok": self.ok,
            "counts": dict(sorted(counts.items())),
            "checks": [check.to_dict() for check in self.checks],
        }


def _check(name: str, status: str, message: str, **metadata: Any) -> DoctorCheck:
    return DoctorCheck(name=name, status=status, message=message, metadata=metadata)


def _path_exists(root: Path, relative: str) -> bool:
    return (root / relative).exists()


def _walk_dirs(root: Path, max_depth: int) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    results: list[Path] = []
    queue: list[tuple[Path, int]] = [(root, 0)]
    while queue:
        path, depth = queue.pop(0)
        if depth > max_depth:
            continue
        results.append(path)
        if depth == max_depth:
            continue
        try:
            children = sorted(child for child in path.iterdir() if child.is_dir())
        except OSError:
            continue
        queue.extend((child, depth + 1) for child in children)
    return results


def _looks_like_ffmpeg(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "libavcodec").is_dir()
        and (path / "libavformat").is_dir()
        and ((path / "fftools").is_dir() or (path / "ffmpeg.c").exists())
    )


def _find_ffmpeg_candidates(roots: list[Path]) -> list[str]:
    candidates: list[str] = []
    for root in roots:
        for path in _walk_dirs(root, max_depth=4):
            if path.name.lower() == "ffmpeg" or _looks_like_ffmpeg(path):
                if _looks_like_ffmpeg(path):
                    candidates.append(path.resolve().as_posix())
    return sorted(set(candidates))


def _ffmpeg_mpeg4_readiness(path: Path) -> DoctorCheck:
    manifest = scan_repository(path)
    file_paths = [item.path for item in manifest.files]
    libavcodec_files = [
        item
        for item in manifest.files
        if item.path.startswith("libavcodec/")
    ]
    mpeg4_candidates = sorted(
        item.path
        for item in libavcodec_files
        if "mpeg4" in item.path.lower() or "mp4v" in item.path.lower()
    )
    source_candidates = [
        item.path
        for item in libavcodec_files
        if item.kind in {"source", "header"}
    ]
    required_modules = {"libavcodec", "libavformat"}
    missing_modules = sorted(required_modules - set(manifest.top_level_modules))
    status = PASS if mpeg4_candidates and not missing_modules else FAIL
    return _check(
        "ffmpeg_mpeg4_readiness",
        status,
        "FFmpeg checkout has MPEG-4 candidates for graph validation." if status == PASS else "FFmpeg checkout is missing MPEG-4 readiness signals.",
        path=path.as_posix(),
        file_count=len(file_paths),
        language_counts=dict(sorted(manifest.language_counts.items())),
        build_files=manifest.build_files,
        missing_modules=missing_modules,
        libavcodec_file_count=len(libavcodec_files),
        libavcodec_source_count=len(source_candidates),
        mpeg4_candidate_count=len(mpeg4_candidates),
        mpeg4_candidates=mpeg4_candidates[:24],
    )


def _ffmpeg_build_context_readiness(path: Path) -> DoctorCheck:
    context = load_build_context(path)
    translation_units = context.translation_units
    libavcodec_units = [
        item
        for item in translation_units
        if item.file.startswith("libavcodec/")
    ]
    mpeg4_units = [
        item.file
        for item in libavcodec_units
        if "mpeg4" in item.file.lower() or "mp4v" in item.file.lower()
    ]
    if not context.compile_commands_path:
        status = PENDING
        message = "FFmpeg compile_commands.json is not available; Clang semantic validation remains pending."
    elif not translation_units:
        status = PENDING
        message = "FFmpeg compile_commands.json contains no translation units."
    elif not mpeg4_units:
        status = WARN
        message = "FFmpeg build context is present but no MPEG-4 libavcodec translation unit was found."
    else:
        status = PASS
        message = "FFmpeg build context is ready for selected Clang semantic validation."
    return _check(
        "ffmpeg_build_context",
        status,
        message,
        path=path.as_posix(),
        compile_commands_path=context.compile_commands_path,
        translation_unit_count=len(translation_units),
        libavcodec_translation_unit_count=len(libavcodec_units),
        mpeg4_translation_unit_count=len(mpeg4_units),
        sample_translation_units=[item.file for item in translation_units[:5]],
        mpeg4_translation_units=mpeg4_units[:12],
    )


def run_doctor(
    workspace: str | Path = ".",
    *,
    ffmpeg_root: str | Path | None = None,
    ffmpeg_search_roots: list[str | Path] | None = None,
) -> DoctorReport:
    root = Path(workspace).resolve()
    checks: list[DoctorCheck] = []

    required_paths = [
        "HARNESS.md",
        "pyproject.toml",
        "expositor",
        "docs/architecture-spec-v0.1.md",
        "docs/roadmap-mvp.md",
        "docs/graph-model.md",
        "docs/ai-contract.md",
        "corpus/tiny-c",
        "corpus/tiny-cpp",
        "tests/test_core.py",
    ]
    missing = [path for path in required_paths if not _path_exists(root, path)]
    checks.append(
        _check(
            "repository_layout",
            FAIL if missing else PASS,
            "Required project files are present." if not missing else "Required project files are missing.",
            missing=missing,
        )
    )

    schema = graph_schema()
    required_node_types = {"Repository", "File", "Function", "Module"}
    required_edge_types = {"CONTAINS", "INCLUDES", "DEPENDS_ON", "CALLS", "UNRESOLVED"}
    required_edge_fields = {
        "source",
        "target",
        "type",
        "confidence",
        "extraction_tool",
        "evidence",
        "build_context",
    }
    schema_missing = {
        "node_types": sorted(required_node_types - set(schema["node_types"])),
        "edge_types": sorted(required_edge_types - set(schema["edge_types"])),
        "edge_fields": sorted(required_edge_fields - set(schema["edge_fields"])),
    }
    schema_ok = (
        schema["project"] == "Code Expositor"
        and schema["package"] == "expositor"
        and schema["evidence_contract"]["graph_is_source_of_truth"]
        and not any(schema_missing.values())
    )
    checks.append(
        _check(
            "canonical_schema",
            PASS if schema_ok else FAIL,
            "Canonical graph schema is executable." if schema_ok else "Canonical graph schema is missing required contract fields.",
            index_version=schema["index_version"],
            missing=schema_missing,
        )
    )

    tiny_c = root / "corpus" / "tiny-c"
    tiny_cpp = root / "corpus" / "tiny-cpp"
    checks.append(
        _check(
            "tiny_corpus",
            PASS if tiny_c.exists() and tiny_cpp.exists() else FAIL,
            "Tiny C and C++ corpora are present." if tiny_c.exists() and tiny_cpp.exists() else "Tiny corpus directories are missing.",
            tiny_c=tiny_c.exists(),
            tiny_cpp=tiny_cpp.exists(),
        )
    )

    graph = None
    if tiny_c.exists():
        try:
            graph = build_canonical_graph(tiny_c, outline_source="auto")
            report = validate_graph(graph)
            if report.issue_counts["error"]:
                status = FAIL
            elif report.issue_counts["warning"]:
                status = WARN
            else:
                status = PASS
            checks.append(
                _check(
                    "tiny_graph_validation",
                    status,
                    "Tiny C canonical graph passes validation." if status == PASS else "Tiny C canonical graph has validation issues.",
                    errors=report.issue_counts["error"],
                    warnings=report.issue_counts["warning"],
                    nodes=report.graph_counts["nodes"],
                    edges=report.graph_counts["edges"],
                )
            )
        except Exception as exc:
            checks.append(
                _check(
                    "tiny_graph_validation",
                    FAIL,
                    "Tiny C canonical graph could not be built.",
                    error=str(exc),
                )
            )

    if graph is not None:
        try:
            case_study = run_mpeg4_case_study(graph)
            matching_symbols = [item["label"] for item in case_study["matching_symbols"]]
            paths = case_study["possible_paths"].get("decode_mpeg4_packet", [])
            implementation_candidates = case_study.get("implementation_candidates", [])
            matching_implementations = [
                item
                for item in implementation_candidates
                if item.get("symbol") == "decode_mpeg4_packet"
                and item.get("role") == "definition"
            ]
            status = PASS if "decode_mpeg4_packet" in matching_symbols and paths and matching_implementations else FAIL
            checks.append(
                _check(
                    "tiny_mpeg4_case_study",
                    status,
                    "Tiny MPEG-4 case study finds an implementation candidate and a static path." if status == PASS else "Tiny MPEG-4 case study is incomplete.",
                    matching_symbols=matching_symbols,
                    implementation_candidates=[
                        {
                            "symbol": item.get("symbol"),
                            "path": item.get("path"),
                            "line": item.get("line"),
                            "role": item.get("role"),
                        }
                        for item in implementation_candidates
                    ],
                    path_count=len(paths),
                )
            )
        except Exception as exc:
            checks.append(
                _check(
                    "tiny_mpeg4_case_study",
                    FAIL,
                    "Tiny MPEG-4 case study failed.",
                    error=str(exc),
                )
            )

        try:
            include_dot = graph_to_dot(graph, "includes")
            call_svg = graph_to_svg(graph, "calls")
            module_svg = graph_to_svg(graph, "modules")
            architecture_svg = graph_to_svg(graph, "architecture")
            html = render_html_report(graph)
            required_sections = [
                "Repository Overview",
                "Module Dependency Diagram",
                "Include Dependency Graph",
                "Selected Call-path Diagram",
                "Architecture Slice Diagram",
                "Symbol Browser",
                "MPEG-4 Case Study",
                "Public API Candidates",
                "Evidence-bound Summary",
            ]
            missing_sections = [
                section for section in required_sections if section not in html
            ]
            has_dot = "digraph" in include_dot and "INCLUDES" in include_dot
            svg_count = sum(
                1
                for svg in [call_svg, module_svg, architecture_svg]
                if "<svg" in svg
            )
            status = PASS if has_dot and svg_count == 3 and not missing_sections else FAIL
            checks.append(
                _check(
                    "tiny_exports_report",
                    status,
                    "Tiny graph exports and HTML report render from the canonical graph." if status == PASS else "Tiny graph exports or HTML report are incomplete.",
                    dot_has_includes=has_dot,
                    svg_count=svg_count,
                    missing_sections=missing_sections,
                    html_svg_count=html.count("<svg"),
                )
            )
        except Exception as exc:
            checks.append(
                _check(
                    "tiny_exports_report",
                    FAIL,
                    "Tiny graph exports or HTML report failed.",
                    error=str(exc),
                )
            )

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                db_path = Path(tmpdir) / "tiny.sqlite"
                save_graph(db_path, graph)
                info = storage_info(db_path)
            counts = info.get("counts") or {}
            adjacency = info.get("adjacency_counts") or {}
            graph_node_count = len(graph.nodes)
            graph_edge_count = len(graph.edges)
            count_ok = (
                info.get("ok") is True
                and counts.get("nodes") == graph_node_count
                and counts.get("edges") == graph_edge_count
                and adjacency.get("out") == graph_edge_count
                and adjacency.get("in") == graph_edge_count
            )
            checks.append(
                _check(
                    "tiny_storage_store",
                    PASS if count_ok else FAIL,
                    "Tiny canonical graph persists to SQLite with matching adjacency." if count_ok else "Tiny SQLite graph store is inconsistent.",
                    nodes=counts.get("nodes"),
                    edges=counts.get("edges"),
                    adjacency_out=adjacency.get("out"),
                    adjacency_in=adjacency.get("in"),
                    issues=info.get("issues") or [],
                )
            )
        except Exception as exc:
            checks.append(
                _check(
                    "tiny_storage_store",
                    FAIL,
                    "Tiny SQLite graph store check failed.",
                    error=str(exc),
                )
            )

    clang_path = shutil.which("clang")
    checks.append(
        _check(
            "clang",
            PASS if clang_path else WARN,
            "Clang is available for semantic spikes." if clang_path else "Clang is unavailable; semantic spike will be skipped.",
            path=clang_path,
        )
    )
    if clang_path and tiny_cpp.exists():
        try:
            semantic = build_clang_semantic_index(tiny_cpp, limit=1)
            calls = {(item.caller, item.callee) for item in semantic.calls}
            has_cpp_call = ("play", "mix_samples") in calls or ("Player::play", "mix_samples") in calls
            status = PASS if semantic.available and not semantic.diagnostics and has_cpp_call else FAIL
            checks.append(
                _check(
                    "tiny_cpp_semantic",
                    status,
                    "Tiny C++ semantic spike extracts method calls." if status == PASS else "Tiny C++ semantic spike is incomplete.",
                    diagnostics=semantic.diagnostics,
                    function_count=len(semantic.functions),
                    call_count=len(semantic.calls),
                )
            )
        except Exception as exc:
            checks.append(
                _check(
                    "tiny_cpp_semantic",
                    FAIL,
                    "Tiny C++ semantic spike failed.",
                    error=str(exc),
                )
            )
    has_tree_sitter = tree_sitter_available()
    checks.append(
        _check(
            "tree_sitter",
            PASS if has_tree_sitter else WARN,
            "tree-sitter runtime is available." if has_tree_sitter else "tree-sitter runtime unavailable; outline auto falls back to regex.",
        )
    )
    has_universal_ctags = universal_ctags_available()
    checks.append(
        _check(
            "universal_ctags",
            PASS if has_universal_ctags else WARN,
            "Universal Ctags is available." if has_universal_ctags else "Universal Ctags unavailable; symbols auto falls back to outline.",
        )
    )
    has_graphviz = graphviz_available()
    checks.append(
        _check(
            "graphviz",
            PASS if has_graphviz else WARN,
            "Graphviz dot is available." if has_graphviz else "Graphviz dot unavailable; SVG auto falls back to internal renderer.",
        )
    )

    if ffmpeg_root:
        ffmpeg_path = Path(ffmpeg_root).resolve()
        is_ffmpeg = _looks_like_ffmpeg(ffmpeg_path)
        checks.append(
            _check(
                "ffmpeg_checkout",
                PASS if is_ffmpeg else FAIL,
                "FFmpeg checkout is present." if is_ffmpeg else "Provided FFmpeg path is not a recognizable checkout.",
                path=ffmpeg_path.as_posix(),
            )
        )
        if is_ffmpeg:
            try:
                checks.append(_ffmpeg_mpeg4_readiness(ffmpeg_path))
            except Exception as exc:
                checks.append(
                    _check(
                        "ffmpeg_mpeg4_readiness",
                        FAIL,
                        "FFmpeg MPEG-4 readiness check failed.",
                        path=ffmpeg_path.as_posix(),
                        error=str(exc),
                    )
                )
            try:
                checks.append(_ffmpeg_build_context_readiness(ffmpeg_path))
            except Exception as exc:
                checks.append(
                    _check(
                        "ffmpeg_build_context",
                        FAIL,
                        "FFmpeg build context readiness check failed.",
                        path=ffmpeg_path.as_posix(),
                        error=str(exc),
                    )
                )
    else:
        search_roots = [Path(item).resolve() for item in ffmpeg_search_roots or [root.parent]]
        candidates = _find_ffmpeg_candidates(search_roots)
        checks.append(
            _check(
                "ffmpeg_checkout",
                PASS if candidates else PENDING,
                "FFmpeg checkout found." if candidates else "FFmpeg checkout not found locally; large validation remains pending.",
                candidates=candidates,
                search_roots=[item.as_posix() for item in search_roots],
            )
        )
        if candidates:
            ffmpeg_path = Path(candidates[0])
            try:
                checks.append(_ffmpeg_mpeg4_readiness(ffmpeg_path))
            except Exception as exc:
                checks.append(
                    _check(
                        "ffmpeg_mpeg4_readiness",
                        FAIL,
                        "FFmpeg MPEG-4 readiness check failed.",
                        path=ffmpeg_path.as_posix(),
                        error=str(exc),
                    )
                )
            try:
                checks.append(_ffmpeg_build_context_readiness(ffmpeg_path))
            except Exception as exc:
                checks.append(
                    _check(
                        "ffmpeg_build_context",
                        FAIL,
                        "FFmpeg build context readiness check failed.",
                        path=ffmpeg_path.as_posix(),
                        error=str(exc),
                    )
                )

    return DoctorReport(
        ok=not any(check.status == FAIL for check in checks),
        checks=checks,
    )
