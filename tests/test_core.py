import json
from pathlib import Path
import shutil
import tempfile
import unittest

from expositor.cli import main as cli_main
from expositor.exporters import (
    dot_to_graphviz_svg,
    graph_to_dot,
    graph_to_svg,
    graphviz_available,
)
from expositor.case_studies import run_mpeg4_case_study
from expositor.doctor import run_doctor
from expositor.explain import (
    build_repository_evidence_payload,
    build_top_down_explanation,
    render_top_down_explanation,
)
from expositor.graph import build_canonical_graph, build_indexes
from expositor.build_context import capture_make_build_context, load_build_context
from expositor.intake import scan_repository
from expositor.model import EdgeType, Graph, NodeType, graph_schema
from expositor.outline import build_outline, tree_sitter_available
from expositor.queries import QueryEngine
from expositor.report import render_html_report
from expositor.semantic import build_clang_semantic_index
from expositor.storage import adjacency_counts, load_graph, save_graph, storage_info
from expositor.symbols import build_symbol_index
from expositor.symbols.ctags import parse_ctags_json_lines
from expositor.validation import validate_graph


ROOT = Path(__file__).resolve().parents[1]
TINY_C = ROOT / "corpus" / "tiny-c"
TINY_CPP = ROOT / "corpus" / "tiny-cpp"


def make_ffmpeg_like_checkout(root: Path) -> Path:
    ffmpeg = root / "ffmpeg"
    (ffmpeg / "libavcodec").mkdir(parents=True)
    (ffmpeg / "libavformat").mkdir()
    (ffmpeg / "fftools").mkdir()
    (ffmpeg / "libavcodec" / "mpeg4videodec.c").write_text(
        "int ff_mpeg4_decode_picture(void) { return 0; }\n",
        encoding="utf-8",
    )
    (ffmpeg / "libavcodec" / "mpeg4video.h").write_text(
        "int ff_mpeg4_decode_picture(void);\n",
        encoding="utf-8",
    )
    (ffmpeg / "libavformat" / "mpeg.c").write_text(
        "int avformat_open_input(void) { return 0; }\n",
        encoding="utf-8",
    )
    (ffmpeg / "fftools" / "ffmpeg.c").write_text(
        "int main(void) { return 0; }\n",
        encoding="utf-8",
    )
    (ffmpeg / "configure").write_text("#!/bin/sh\n", encoding="utf-8")
    return ffmpeg


def write_ffmpeg_compile_commands(ffmpeg: Path) -> None:
    payload = [
        {
            "directory": ffmpeg.as_posix(),
            "file": "libavcodec/mpeg4videodec.c",
            "arguments": [
                "clang",
                "-I.",
                "-Ilibavcodec",
                "-DFFMPEG_TEST_BUILD=1",
                "-c",
                "libavcodec/mpeg4videodec.c",
                "-o",
                "libavcodec/mpeg4videodec.o",
            ],
        }
    ]
    (ffmpeg / "compile_commands.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


class IntakeTests(unittest.TestCase):
    def test_scan_repository_inventory(self):
        manifest = scan_repository(TINY_C)

        paths = {item.path for item in manifest.files}
        self.assertIn("src/main.c", paths)
        self.assertIn("include/codec.h", paths)
        self.assertIn("README.md", paths)
        self.assertIn("compile_commands.json", manifest.build_files)
        self.assertGreaterEqual(manifest.language_counts["c"], 3)
        self.assertEqual("documentation", [item.kind for item in manifest.files if item.path == "README.md"][0])


class CoreGraphTests(unittest.TestCase):
    def test_root_package_exports_core_public_api(self):
        import expositor

        self.assertEqual("0.1.0", expositor.__version__)
        self.assertIs(expositor.Graph, Graph)
        self.assertIs(expositor.NodeType, NodeType)
        self.assertIs(expositor.EdgeType, EdgeType)
        self.assertIs(expositor.graph_schema, graph_schema)
        self.assertTrue(callable(expositor.build_canonical_graph))
        self.assertTrue(callable(expositor.scan_repository))
        self.assertTrue(callable(expositor.validate_graph))

    def test_graph_schema_is_executable_contract(self):
        schema = graph_schema()

        self.assertEqual("Code Expositor", schema["project"])
        self.assertEqual("0.1", schema["index_version"])
        self.assertIn("Repository", schema["node_types"])
        self.assertIn("Function", schema["node_types"])
        self.assertIn("CALLS", schema["edge_types"])
        self.assertIn("UNRESOLVED", schema["edge_types"])
        self.assertIn("CONFIRMED", schema["confidence_labels"])
        self.assertIn("UNRESOLVED", schema["confidence_labels"])
        self.assertTrue(schema["evidence_contract"]["graph_is_source_of_truth"])
        for field_name in [
            "source",
            "target",
            "type",
            "confidence",
            "extraction_tool",
            "evidence",
            "build_context",
        ]:
            self.assertIn(field_name, schema["edge_fields"])

    def test_schema_cli_emits_canonical_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "schema.json"
            exit_code = cli_main(["schema", "--output", str(output)])

            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("Expositor Core", payload["schema_owner"])
            self.assertIn("HeaderFile", payload["node_types"])
            self.assertIn("DEPENDS_ON", payload["edge_types"])

    def test_indexes_extract_symbols_includes_calls_and_architecture(self):
        indexes = build_indexes(TINY_C)

        symbol_names = {item.name for item in indexes.symbols.symbols}
        self.assertIn("decode_frame", symbol_names)
        self.assertIn("decode_mpeg4_packet", symbol_names)

        includes = {(item.source, item.resolved) for item in indexes.includes.includes}
        self.assertIn(("src/main.c", "include/codec.h"), includes)

        calls = {(item.caller, item.callee) for item in indexes.call_graph.calls}
        self.assertIn(("main", "decoder_init"), calls)
        self.assertIn(("decode_frame", "decode_mpeg4_packet"), calls)
        self.assertIn(("probe_external_decoder", "external_decoder_probe"), calls)
        unresolved = [
            item
            for item in indexes.call_graph.calls
            if item.caller == "probe_external_decoder"
        ]
        self.assertEqual("UNRESOLVED", unresolved[0].confidence)

        arches = {(item.file, item.architecture) for item in indexes.architecture.matches}
        self.assertIn(("arch/x86/simd.c", "x86"), arches)
        doc_text = " ".join(item.text for item in indexes.documentation.snippets)
        self.assertIn("MPEG-4 packet decoder", doc_text)

    def test_outline_auto_source_uses_tree_sitter_boundary_or_fallback(self):
        outline = build_outline(TINY_C, source="auto")

        names = {item.name for item in outline.items}
        self.assertIn("decode_frame", names)
        self.assertIn(outline.source, {"tree-sitter", "outline-regex"})
        if not tree_sitter_available():
            self.assertEqual("outline-regex", outline.source)
            self.assertTrue(any("tree-sitter" in item for item in outline.diagnostics))

    def test_outline_cli_supports_auto_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "outline.json"
            exit_code = cli_main(
                [
                    "outline",
                    str(TINY_C),
                    "--source",
                    "auto",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            names = {
                item["name"]
                for file_outline in payload["files"]
                for item in file_outline["items"]
            }
            self.assertIn("decode_frame", names)
            self.assertIn(payload["source"], {"tree-sitter", "outline-regex"})

    def test_query_paths_storage_exports_and_report(self):
        graph = build_canonical_graph(TINY_C)
        query = QueryEngine(graph)

        callers = query.callers_of("decode_mpeg4_packet")["callers"]
        self.assertTrue(any(item["source"]["label"] == "decode_frame" for item in callers))

        unresolved = query.callees_of("probe_external_decoder")["callees"]
        self.assertTrue(any(item["edge"]["type"] == "UNRESOLVED" for item in unresolved))

        src_module = query.module_summary("src")
        self.assertTrue(
            any(
                item["target"]["label"] == "include"
                and item["edge"]["type"] == "DEPENDS_ON"
                for item in src_module["outgoing_dependencies"]
            )
        )

        compiler_flags = {node.label for node in graph.nodes_of_type(NodeType.COMPILER_FLAG)}
        feature_flags = {node.label for node in graph.nodes_of_type(NodeType.FEATURE_FLAG)}
        architectures = {node.label for node in graph.nodes_of_type(NodeType.ARCHITECTURE)}
        self.assertIn("-Iinclude", compiler_flags)
        self.assertIn("DEBUG=1", feature_flags)
        self.assertIn("x86_64-linux-gnu", architectures)
        call_edges = [
            item["edge"]
            for item in query.callees_of("main")["callees"]
            if item["target"]["label"] == "decode_frame"
        ]
        self.assertEqual("src/main.c", call_edges[0]["build_context"])

        paths = query.paths_to("decode_mpeg4_packet", max_depth=4)["paths"]
        labels = [[node["label"] for node in path] for path in paths]
        self.assertIn(["main", "decode_frame", "decode_mpeg4_packet"], labels)

        dot = graph_to_dot(graph, "includes")
        self.assertIn("INCLUDES", dot)
        module_dot = graph_to_dot(graph, "modules")
        self.assertIn("DEPENDS_ON", module_dot)
        self.assertIn("src", module_dot)
        self.assertIn("include", module_dot)
        self.assertNotIn("decoder.c", module_dot)

        svg = graph_to_svg(graph, "calls")
        self.assertIn("<svg", svg)
        auto_svg = graph_to_svg(graph, "calls", renderer="auto")
        self.assertIn("<svg", auto_svg)
        self.assertFalse(graphviz_available("__missing_dot__"))
        with self.assertRaises(RuntimeError):
            dot_to_graphviz_svg("digraph G {}\n", executable="__missing_dot__")

        html = render_html_report(graph)
        self.assertIn("Repository Overview", html)
        self.assertIn("Module Dependency Diagram", html)
        self.assertIn("Include Dependency Graph", html)
        self.assertIn("Selected Call-path Diagram", html)
        self.assertIn("Architecture Slice Diagram", html)
        self.assertIn("Module Dependencies", html)
        self.assertIn("Build Context", html)
        self.assertIn("MPEG-4 Case Study", html)
        self.assertIn("Implementation Candidates", html)
        self.assertIn("Public API Candidates", html)
        self.assertIn("PublicAPI", html)
        self.assertIn("definition", html)
        self.assertIn("main -&gt; decode_frame -&gt; decode_mpeg4_packet", html)
        self.assertIn("Evidence-bound Summary", html)
        self.assertIn("decode_mpeg4_packet", html)
        self.assertGreaterEqual(html.count("<svg"), 4)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "graph.sqlite"
            save_graph(db_path, graph)
            loaded = load_graph(db_path)
            self.assertEqual(len(graph.nodes), len(loaded.nodes))
            self.assertEqual(len(graph.edges), len(loaded.edges))
            counts = adjacency_counts(db_path)
            self.assertEqual(len(graph.edges), counts["out"])
            self.assertEqual(len(graph.edges), counts["in"])
            info = storage_info(db_path)
            self.assertTrue(info["ok"])
            self.assertEqual(len(graph.nodes), info["counts"]["nodes"])
            self.assertEqual(len(graph.edges), info["counts"]["edges"])
            self.assertEqual(len(graph.edges), info["adjacency_counts"]["out"])
            self.assertIn("CALLS", info["edge_type_counts"])

            info_output = Path(tmpdir) / "store-info.json"
            exit_code = cli_main(
                [
                    "store-info",
                    str(db_path),
                    "--format",
                    "json",
                    "--output",
                    str(info_output),
                ]
            )
            self.assertEqual(0, exit_code)
            info_payload = json.loads(info_output.read_text(encoding="utf-8"))
            self.assertTrue(info_payload["ok"])
            self.assertEqual(len(graph.edges), info_payload["counts"]["edges"])

    def test_graph_validation_quality_gate(self):
        graph = build_canonical_graph(TINY_C)
        report = validate_graph(graph)

        self.assertTrue(report.ok)
        self.assertEqual(0, report.issue_counts["error"])

        broken = Graph()
        repo = broken.add_node(NodeType.REPOSITORY, "broken")
        broken.add_edge(
            repo,
            "missing-target",
            EdgeType.CONTAINS,
            extraction_tool="test",
        )
        broken_report = validate_graph(broken)
        self.assertFalse(broken_report.ok)
        self.assertTrue(
            any(issue.code == "edge_missing_target" for issue in broken_report.issues)
        )

    def test_validate_cli_exposes_quality_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "validation.json"
            exit_code = cli_main(
                [
                    "validate",
                    str(TINY_C),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(0, payload["issue_counts"]["error"])

    def test_doctor_reports_local_milestone_gates(self):
        report = run_doctor(ROOT)
        payload = report.to_dict()
        checks = {item["name"]: item for item in payload["checks"]}

        self.assertTrue(payload["ok"])
        self.assertEqual("pass", checks["canonical_schema"]["status"])
        self.assertEqual("pass", checks["repository_layout"]["status"])
        self.assertEqual("pass", checks["tiny_corpus"]["status"])
        self.assertEqual("pass", checks["tiny_graph_validation"]["status"])
        self.assertEqual("pass", checks["tiny_mpeg4_case_study"]["status"])
        self.assertEqual("pass", checks["tiny_exports_report"]["status"])
        self.assertEqual("pass", checks["tiny_storage_store"]["status"])
        self.assertEqual(
            checks["tiny_storage_store"]["metadata"]["edges"],
            checks["tiny_storage_store"]["metadata"]["adjacency_out"],
        )
        self.assertEqual(
            checks["tiny_storage_store"]["metadata"]["edges"],
            checks["tiny_storage_store"]["metadata"]["adjacency_in"],
        )
        self.assertEqual(3, checks["tiny_exports_report"]["metadata"]["svg_count"])
        self.assertEqual([], checks["tiny_exports_report"]["metadata"]["missing_sections"])
        implementations = {
            (item["symbol"], item["path"], item["role"])
            for item in checks["tiny_mpeg4_case_study"]["metadata"]["implementation_candidates"]
        }
        self.assertIn(
            ("decode_mpeg4_packet", "src/decoder.c", "definition"),
            implementations,
        )
        self.assertIn(checks["ffmpeg_checkout"]["status"], {"pass", "pending"})

    @unittest.skipIf(shutil.which("make") is None, "make not available")
    def test_build_context_can_capture_make_dry_run_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "include").mkdir()
            (root / "src").mkdir()
            (root / "src" / "mpeg4.c").write_text("int decode(void) { return 0; }\n", encoding="utf-8")
            (root / "Makefile").write_text(
                "src/mpeg4.o:\n"
                "\tclang -Iinclude -DTEST_MACRO=1 -MMD -MF src/mpeg4.d -MT src/mpeg4.o -c -o src/mpeg4.o src/mpeg4.c\n",
                encoding="utf-8",
            )

            context = capture_make_build_context(root, ["src/mpeg4.o"])

            self.assertIsNone(context.compile_commands_path)
            self.assertEqual(1, len(context.translation_units))
            command = context.translation_units[0]
            self.assertEqual("src/mpeg4.c", command.file)
            self.assertIn("include", command.include_paths)
            self.assertIn("TEST_MACRO=1", command.macros)

    @unittest.skipIf(shutil.which("make") is None, "make not available")
    def test_build_context_cli_writes_captured_compile_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "include").mkdir()
            (root / "src").mkdir()
            (root / "src" / "mpeg4.c").write_text("int decode(void) { return 0; }\n", encoding="utf-8")
            (root / "Makefile").write_text(
                "src/mpeg4.o:\n"
                "\tclang -Iinclude -DTEST_MACRO=1 -c -o src/mpeg4.o src/mpeg4.c\n",
                encoding="utf-8",
            )
            output = root / "context.json"
            exit_code = cli_main(
                [
                    "build-context",
                    str(root),
                    "--make-target",
                    "src/mpeg4.o",
                    "--write-compile-commands",
                    "compile_commands.json",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("compile_commands.json", payload["compile_commands_path"])
            loaded = load_build_context(root)
            self.assertEqual("compile_commands.json", loaded.compile_commands_path)
            self.assertEqual("src/mpeg4.c", loaded.translation_units[0].file)

    def test_doctor_cli_emits_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "doctor.json"
            exit_code = cli_main(
                [
                    "doctor",
                    str(ROOT),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            names = {item["name"] for item in payload["checks"]}
            self.assertIn("canonical_schema", names)
            self.assertIn("ffmpeg_checkout", names)

    def test_doctor_cli_text_includes_ffmpeg_readiness_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ffmpeg = make_ffmpeg_like_checkout(Path(tmpdir))
            output = Path(tmpdir) / "doctor.txt"
            exit_code = cli_main(
                [
                    "doctor",
                    str(ROOT),
                    "--ffmpeg-root",
                    str(ffmpeg),
                    "--format",
                    "text",
                    "--output",
                    str(output),
                ]
            )

            text = output.read_text(encoding="utf-8")
            self.assertEqual(0, exit_code)
            self.assertIn("ffmpeg_checkout: FFmpeg checkout is present.", text)
            self.assertIn("ffmpeg_mpeg4_readiness", text)
            self.assertIn("MPEG-4 candidates:", text)
            self.assertIn("libavcodec/mpeg4videodec.c", text)
            self.assertIn("ffmpeg_build_context", text)
            self.assertIn("compile commands: <missing>", text)

    def test_doctor_ffmpeg_root_checks_mpeg4_readiness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ffmpeg = make_ffmpeg_like_checkout(Path(tmpdir))

            report = run_doctor(ROOT, ffmpeg_root=ffmpeg)
            payload = report.to_dict()
            checks = {item["name"]: item for item in payload["checks"]}

            self.assertTrue(payload["ok"])
            self.assertEqual("pass", checks["ffmpeg_checkout"]["status"])
            self.assertEqual("pass", checks["ffmpeg_mpeg4_readiness"]["status"])
            self.assertEqual("pending", checks["ffmpeg_build_context"]["status"])
            metadata = checks["ffmpeg_mpeg4_readiness"]["metadata"]
            self.assertEqual([], metadata["missing_modules"])
            self.assertGreaterEqual(metadata["mpeg4_candidate_count"], 2)
            self.assertIn("libavcodec/mpeg4videodec.c", metadata["mpeg4_candidates"])

    def test_doctor_ffmpeg_build_context_passes_with_mpeg4_compile_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ffmpeg = make_ffmpeg_like_checkout(Path(tmpdir))
            write_ffmpeg_compile_commands(ffmpeg)

            report = run_doctor(ROOT, ffmpeg_root=ffmpeg)
            payload = report.to_dict()
            checks = {item["name"]: item for item in payload["checks"]}

            self.assertTrue(payload["ok"])
            self.assertEqual("pass", checks["ffmpeg_build_context"]["status"])
            metadata = checks["ffmpeg_build_context"]["metadata"]
            self.assertEqual("compile_commands.json", metadata["compile_commands_path"])
            self.assertEqual(1, metadata["translation_unit_count"])
            self.assertEqual(1, metadata["libavcodec_translation_unit_count"])
            self.assertEqual(1, metadata["mpeg4_translation_unit_count"])
            self.assertEqual(
                ["libavcodec/mpeg4videodec.c"],
                metadata["mpeg4_translation_units"],
            )

    def test_top_down_explanation_is_evidence_bound(self):
        graph = build_canonical_graph(TINY_C)
        explanation = build_top_down_explanation(graph)
        rendered = render_top_down_explanation(explanation)

        self.assertEqual("top_down_explanation", explanation["graph_query"])
        self.assertIn("Module responsibilities", rendered)
        self.assertIn("Dependency summary", rendered)
        self.assertIn("Uncertainty", rendered)
        self.assertIn("Documentation signals", rendered)
        self.assertIn("Decoder Flow", rendered)
        self.assertTrue(explanation["evidence"])
        self.assertTrue(explanation["documentation_signals"])
        modules = {item["module"] for item in explanation["module_responsibilities"]}
        self.assertEqual({"arch", "include", "src"}, modules)

    def test_repository_ai_payload_matches_contract(self):
        graph = build_canonical_graph(TINY_C)
        payload = build_repository_evidence_payload(graph)

        self.assertEqual("repository_evidence_payload", payload["graph_query"])
        self.assertTrue(payload["nodes"])
        self.assertTrue(payload["edges"])
        self.assertTrue(payload["evidence"])
        self.assertTrue(payload["file_locations"])
        self.assertTrue(payload["symbol_locations"])
        self.assertIn("CONFIRMED", payload["confidence"])
        edge = payload["edges"][0]
        self.assertIn("confidence", edge)
        self.assertIn("extraction_tool", edge)
        self.assertIn("evidence", edge)
        self.assertIn(
            "src/decoder.c",
            {item["path"] for item in payload["file_locations"]},
        )
        self.assertIn(
            "decode_mpeg4_packet",
            {item["name"] for item in payload["symbol_locations"]},
        )

    def test_explain_cli_can_emit_ai_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "payload.json"
            exit_code = cli_main(
                [
                    "explain",
                    "repository",
                    str(TINY_C),
                    "--format",
                    "payload",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("repository_evidence_payload", payload["graph_query"])
            self.assertTrue(payload["nodes"])
            self.assertTrue(payload["edges"])
            self.assertTrue(payload["file_locations"])
            self.assertTrue(payload["symbol_locations"])

    def test_explain_text_distinguishes_edge_confidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "explain.txt"
            exit_code = cli_main(
                [
                    "explain",
                    "function",
                    str(TINY_C),
                    "--value",
                    "decode_frame",
                    "--format",
                    "text",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            text = output.read_text(encoding="utf-8")
            self.assertIn("Confidence", text)
            self.assertIn("CONFIRMED", text)
            self.assertIn("LIKELY", text)

    def test_explain_cli_supports_contract_subjects(self):
        cases = [
            ("module", "src", "module_summary"),
            ("file", "src/decoder.c", "file_summary"),
            ("function", "decode_frame", "function_summary"),
            ("path", "decode_mpeg4_packet", "paths_to"),
            ("architecture", "x86", "architecture_slice"),
            ("where", "decode_mpeg4_packet", "where_implemented"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            for subject, value, graph_query in cases:
                output = Path(tmpdir) / f"{subject}.json"
                exit_code = cli_main(
                    [
                        "explain",
                        subject,
                        str(TINY_C),
                        "--value",
                        value,
                        "--format",
                        "payload",
                        "--output",
                        str(output),
                    ]
                )

                self.assertEqual(0, exit_code, subject)
                payload = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(graph_query, payload["graph_query"])
                self.assertTrue(payload["nodes"], subject)
                self.assertTrue(payload["limitations"], subject)

            path_payload = json.loads((Path(tmpdir) / "path.json").read_text(encoding="utf-8"))
            self.assertTrue(
                any(edge["type"] == "CALLS" for edge in path_payload["edges"])
            )
            self.assertTrue(path_payload["evidence"])

    def test_query_cli_exposes_query_api(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "symbols.json"
            exit_code = cli_main(
                [
                    "query",
                    "symbols-in",
                    str(TINY_C),
                    "--value",
                    "src",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            names = {item["label"] for item in payload["symbols"]}
            self.assertIn("decode_frame", names)

    def test_direct_query_cli_commands_cover_query_api(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            commands = [
                (
                    "public-api",
                    ["include", str(TINY_C), "--format", "json"],
                    "public_api",
                    "decode_mpeg4_packet",
                ),
                (
                    "includes-of",
                    ["src/decoder.c", str(TINY_C), "--format", "json"],
                    "includes",
                    "codec.h",
                ),
                (
                    "dependents-of",
                    ["include/codec.h", str(TINY_C), "--format", "json"],
                    "dependents",
                    "decoder.c",
                ),
                (
                    "paths-from",
                    ["main", "decode_mpeg4_packet", str(TINY_C), "--format", "json"],
                    "paths",
                    "decode_frame",
                ),
                (
                    "why-reachable",
                    ["decode_mpeg4_packet", str(TINY_C), "--format", "json"],
                    "paths",
                    "main",
                ),
                (
                    "evidence-for",
                    ["src/decoder.c", str(TINY_C), "--format", "json"],
                    "related_edges",
                    "DEFINES",
                ),
            ]
            for command, args, key, expected in commands:
                output = Path(tmpdir) / f"{command}.json"
                exit_code = cli_main([command, *args, "--output", str(output)])

                self.assertEqual(0, exit_code, command)
                payload = json.loads(output.read_text(encoding="utf-8"))
                self.assertIn(key, payload, command)
                self.assertIn(expected, json.dumps(payload), command)

    def test_universal_ctags_json_parser_and_auto_fallback(self):
        text = "\n".join(
            [
                json.dumps(
                    {
                        "_type": "tag",
                        "name": "decode_frame",
                        "path": "src/decoder.c",
                        "line": 5,
                        "kind": "function",
                        "signature": "(const char *packet)",
                    }
                ),
                json.dumps(
                    {
                        "_type": "tag",
                        "name": "decoder_init",
                        "path": "include/codec.h",
                        "line": 4,
                        "kind": "prototype",
                        "pattern": "/^int decoder_init(void);$/",
                    }
                ),
            ]
        )
        parsed = parse_ctags_json_lines(text, TINY_C)
        by_name = {item.name: item for item in parsed}

        self.assertEqual("Function", by_name["decode_frame"].kind)
        self.assertTrue(by_name["decode_frame"].definition)
        self.assertTrue(by_name["decoder_init"].declaration)
        self.assertEqual("universal-ctags", by_name["decoder_init"].extraction_tool)

        auto_index = build_symbol_index(TINY_C, source="auto")
        names = {item.name for item in auto_index.symbols}
        self.assertIn("decode_frame", names)

    def test_symbols_cli_supports_auto_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "symbols.json"
            exit_code = cli_main(
                [
                    "symbols",
                    str(TINY_C),
                    "--source",
                    "auto",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            names = {item["name"] for item in payload["symbols"]}
            self.assertIn("decode_frame", names)

    def test_paths_to_svg_cli_renders_selected_path_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "path.svg"
            exit_code = cli_main(
                [
                    "paths-to",
                    "decode_mpeg4_packet",
                    str(TINY_C),
                    "--format",
                    "svg",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            svg = output.read_text(encoding="utf-8")
            self.assertIn("decode_frame", svg)
            self.assertIn("decode_mpeg4_packet", svg)
            self.assertNotIn("external_decoder_probe", svg)

    def test_mpeg4_case_study_ranks_decoder_candidates_above_path_only_matches(self):
        graph = Graph()
        graph.add_node(
            NodeType.FUNCTION,
            "scan_buffer",
            path="libavcodec/bsf/mpeg4_unpack_bframes.c",
            metadata={"line": 33, "definition": True},
        )
        graph.add_node(
            NodeType.FUNCTION,
            "decode_new_pred",
            path="libavcodec/mpeg4videodec.c",
            metadata={"line": 693, "definition": True},
        )
        graph.add_node(
            NodeType.FUNCTION,
            "ff_mpeg4_decode_video_packet_header",
            path="libavcodec/mpeg4videodec.h",
            metadata={"line": 121, "declaration": True},
        )

        result = run_mpeg4_case_study(graph)
        candidates = result["implementation_candidates"]

        self.assertEqual("decode_new_pred", candidates[0]["symbol"])
        self.assertEqual("definition", candidates[0]["role"])
        self.assertGreater(candidates[0]["rank_score"], candidates[1]["rank_score"])
        self.assertIn("mpeg4-video-decoder-path", candidates[0]["match_basis"])

    def test_mpeg4_case_study_uses_graph_evidence(self):
        graph = build_canonical_graph(TINY_C)
        result = run_mpeg4_case_study(graph)

        symbols = {item["label"] for item in result["matching_symbols"]}
        self.assertIn("decode_mpeg4_packet", symbols)
        implementation_candidates = {
            (item["symbol"], item["path"], item["role"])
            for item in result["implementation_candidates"]
        }
        self.assertIn(
            ("decode_mpeg4_packet", "src/decoder.c", "definition"),
            implementation_candidates,
        )
        public_api_candidates = {
            (item["label"], item["type"], item["path"])
            for item in result["public_api_candidates"]
        }
        self.assertIn(
            ("decode_mpeg4_packet", "PublicAPI", "include/codec.h"),
            public_api_candidates,
        )
        paths = result["possible_paths"]["decode_mpeg4_packet"]
        labels = [[node["label"] for node in path] for path in paths]
        self.assertIn(["main", "decode_frame", "decode_mpeg4_packet"], labels)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "mpeg4.txt"
            exit_code = cli_main(
                [
                    "case-study",
                    "mpeg4",
                    str(TINY_C),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(0, exit_code)
            text = output.read_text(encoding="utf-8")
            self.assertIn("Public API candidates", text)
            self.assertIn("decode_mpeg4_packet [PublicAPI] include/codec.h:11", text)

    @unittest.skipIf(shutil.which("clang") is None, "clang not available")
    def test_clang_semantic_spike_extracts_direct_calls(self):
        semantic = build_clang_semantic_index(TINY_C, limit=2)

        self.assertTrue(semantic.available)
        self.assertEqual([], semantic.diagnostics)
        calls = {(item.caller, item.callee) for item in semantic.calls}
        self.assertIn(("decode_frame", "decode_mpeg4_packet"), calls)
        self.assertIn(("main", "decode_frame"), calls)

    @unittest.skipIf(shutil.which("clang") is None, "clang not available")
    def test_clang_semantic_overlay_merges_into_canonical_graph(self):
        graph = build_canonical_graph(TINY_C, semantic=True, semantic_limit=2)

        semantic_edges = [
            edge
            for edge in graph.edges.values()
            if edge.extraction_tool == "clang-ast"
        ]
        self.assertTrue(
            any(
                graph.nodes[edge.source].label == "decode_frame"
                and graph.nodes[edge.target].label == "decode_mpeg4_packet"
                for edge in semantic_edges
            )
        )
        semantic_definition_edges = [
            edge
            for edge in graph.edges.values()
            if edge.extraction_tool == "clang-ast"
            and edge.type in {EdgeType.DEFINES.value, EdgeType.DECLARES.value}
        ]
        self.assertTrue(
            any(
                graph.nodes[edge.target].label == "decode_mpeg4_packet"
                and graph.nodes[edge.target].metadata["line"] == 11
                and graph.nodes[edge.target].metadata["semantic"] is True
                for edge in semantic_definition_edges
            )
        )
        repo = graph.nodes_of_type(NodeType.REPOSITORY)[0]
        self.assertEqual(True, repo.metadata["semantic"]["enabled"])
        self.assertEqual(3, repo.metadata["semantic"]["call_count"])
        html = render_html_report(graph)
        self.assertIn("clang-ast", html)

    @unittest.skipIf(shutil.which("clang") is None, "clang not available")
    def test_graph_cli_accepts_semantic_overlay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "graph.json"
            exit_code = cli_main(
                [
                    "graph",
                    str(TINY_C),
                    "--semantic",
                    "--semantic-limit",
                    "2",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            semantic_edges = [
                item
                for item in payload["edges"]
                if item["extraction_tool"] == "clang-ast"
            ]
            self.assertTrue(semantic_edges)


class CppOutlineTests(unittest.TestCase):
    def test_cpp_method_and_function_are_indexed(self):
        indexes = build_indexes(TINY_CPP)
        symbol_names = {item.name for item in indexes.symbols.symbols}

        self.assertIn("mix_samples", symbol_names)
        self.assertIn("Player::play", symbol_names)

        context = load_build_context(TINY_CPP)
        self.assertEqual("compile_commands.json", context.compile_commands_path)
        self.assertEqual(["src/player.cpp"], [item.file for item in context.translation_units])

    @unittest.skipIf(shutil.which("clang") is None, "clang not available")
    def test_cpp_clang_semantic_spike_extracts_method_calls(self):
        semantic = build_clang_semantic_index(TINY_CPP, limit=1)

        self.assertTrue(semantic.available)
        self.assertEqual([], semantic.diagnostics)
        calls = {(item.caller, item.callee) for item in semantic.calls}
        self.assertTrue(
            ("play", "mix_samples") in calls
            or ("Player::play", "mix_samples") in calls
        )

    @unittest.skipIf(shutil.which("clang") is None, "clang not available")
    def test_cpp_semantic_overlay_merges_into_canonical_graph(self):
        graph = build_canonical_graph(TINY_CPP, semantic=True, semantic_limit=1)

        semantic_edges = [
            edge
            for edge in graph.edges.values()
            if edge.extraction_tool == "clang-ast"
        ]
        self.assertTrue(
            any(
                graph.nodes[edge.source].label == "Player::play"
                and graph.nodes[edge.target].label == "mix_samples"
                for edge in semantic_edges
            )
        )
        report = validate_graph(graph)
        self.assertTrue(report.ok)
        self.assertEqual(0, report.issue_counts["error"])


if __name__ == "__main__":
    unittest.main()
