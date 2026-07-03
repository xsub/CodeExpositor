"""Assemble extractor outputs into the canonical graph."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from expositor.architecture import ArchitectureIndex, classify_architecture
from expositor.build_context import BuildContext, load_build_context
from expositor.callgraph import DirectCallGraph, build_call_graph
from expositor.documentation import DocumentationIndex, extract_documentation
from expositor.includes import IncludeGraph, build_include_graph
from expositor.intake import RepositoryManifest, scan_repository
from expositor.model import Confidence, EdgeType, Evidence, Graph, Node, NodeType, stable_id
from expositor.outline import OutlineIndex, build_outline
from expositor.semantic import ClangSemanticIndex, build_clang_semantic_index
from expositor.symbols import SymbolIndex, SymbolRecord, build_symbol_index


@dataclass
class CoreIndexes:
    manifest: RepositoryManifest
    outline: OutlineIndex
    symbols: SymbolIndex
    includes: IncludeGraph
    build_context: BuildContext
    call_graph: DirectCallGraph
    architecture: ArchitectureIndex
    documentation: DocumentationIndex

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "outline": self.outline.to_dict(),
            "symbols": self.symbols.to_dict(),
            "includes": self.includes.to_dict(),
            "build_context": self.build_context.to_dict(),
            "call_graph": self.call_graph.to_dict(),
            "architecture": self.architecture.to_dict(),
            "documentation": self.documentation.to_dict(),
        }


def build_indexes(
    root: str | Path,
    *,
    outline_source: str = "regex",
    symbol_source: str = "outline",
) -> CoreIndexes:
    root_path = Path(root).resolve()
    manifest = scan_repository(root_path)
    outline = build_outline(root_path, source=outline_source)
    symbols = build_symbol_index(root_path, outline, source=symbol_source)
    includes = build_include_graph(root_path)
    build_context = load_build_context(root_path)
    call_graph = build_call_graph(root_path, symbols)
    architecture = classify_architecture(root_path)
    documentation = extract_documentation(root_path)
    return CoreIndexes(
        manifest=manifest,
        outline=outline,
        symbols=symbols,
        includes=includes,
        build_context=build_context,
        call_graph=call_graph,
        architecture=architecture,
        documentation=documentation,
    )


def _node_type_for_file(kind: str) -> NodeType:
    if kind == "source":
        return NodeType.SOURCE_FILE
    if kind == "header":
        return NodeType.HEADER_FILE
    return NodeType.FILE


def _node_type_for_symbol(symbol: SymbolRecord) -> NodeType:
    mapping = {
        "Function": NodeType.FUNCTION,
        "Method": NodeType.METHOD,
        "Macro": NodeType.MACRO,
        "Struct": NodeType.STRUCT,
        "Class": NodeType.CLASS,
        "Enum": NodeType.ENUM,
        "Typedef": NodeType.TYPEDEF,
    }
    return mapping.get(symbol.kind, NodeType.SYMBOL)


def _parent_dir(path: str) -> str | None:
    parent = Path(path).parent.as_posix()
    return None if parent == "." else parent


def _directory(path: str) -> str:
    parent = Path(path).parent.as_posix()
    return "." if parent == "." else parent


def _top_level(path: str | None) -> str | None:
    if not path or path.startswith("<"):
        return None
    parts = Path(path).parts
    return parts[0] if parts else None


def _evidence(path: str, line: int | None = None, snippet: str | None = None) -> list[Evidence]:
    return [Evidence(path=path, line=line, snippet=snippet)]


def _snippet(root: Path, path: str, line: int | None) -> str | None:
    if not line:
        return None
    try:
        lines = (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()
    return None


def _macro_metadata(macro: str) -> dict[str, Any]:
    if "=" in macro:
        name, value = macro.split("=", 1)
    else:
        name, value = macro, None
    return {"kind": "macro_definition", "name": name, "value": value}


def _add_contains_edges(
    graph: Graph,
    repo_node: Node,
    dir_nodes: dict[str, Node],
    file_nodes: dict[str, Node],
) -> None:
    for path, node in dir_nodes.items():
        parent = _parent_dir(path)
        source = dir_nodes.get(parent) if parent else repo_node
        graph.add_edge(
            source,
            node,
            EdgeType.CONTAINS,
            extraction_tool="repository-intake",
            confidence=Confidence.CONFIRMED,
        )
    for path, node in file_nodes.items():
        parent = _parent_dir(path)
        source = dir_nodes.get(parent) if parent else repo_node
        graph.add_edge(
            source,
            node,
            EdgeType.CONTAINS,
            extraction_tool="repository-intake",
            confidence=Confidence.CONFIRMED,
        )


def _symbol_node_id(symbol: SymbolRecord) -> str:
    return stable_id("symbol", symbol.kind, symbol.file, symbol.line, symbol.name)


def _add_semantic_calls(
    graph: Graph,
    semantic: ClangSemanticIndex,
    root: Path,
    function_defs_by_name: dict[str, Node],
    file_nodes: dict[str, Node],
    build_context_by_file: dict[str, str],
) -> None:
    semantic_functions_by_name: dict[str, Node] = {}
    semantic_functions_by_name_file: dict[tuple[str, str], Node] = {}
    for function in semantic.functions:
        node_type = NodeType.METHOD if function.kind.startswith("CXX") else NodeType.FUNCTION
        existing = function_defs_by_name.get(function.name)
        node = existing or graph.add_node(
            node_type,
            function.name,
            path=function.file,
            metadata={
                "line": function.line,
                "kind": function.kind,
                "definition": function.definition,
                "declaration": not function.definition,
                "signature": function.signature,
                "semantic": True,
            },
        )
        node.metadata.update(
            {
                "line": function.line,
                "kind": function.kind,
                "definition": function.definition,
                "declaration": not function.definition,
                "signature": function.signature,
                "semantic": True,
            }
        )
        if function.definition:
            function_defs_by_name.setdefault(function.name, node)
            function_defs_by_name.setdefault(function.name.rsplit("::", 1)[-1], node)
        semantic_functions_by_name.setdefault(function.name, node)
        semantic_functions_by_name.setdefault(function.name.rsplit("::", 1)[-1], node)
        semantic_functions_by_name_file[(function.name, function.file)] = node
        file_node = file_nodes.get(function.file)
        if file_node:
            graph.add_edge(
                file_node,
                node,
                EdgeType.DEFINES if function.definition else EdgeType.DECLARES,
                extraction_tool="clang-ast",
                confidence=Confidence.CONFIRMED if function.definition else Confidence.LIKELY,
                evidence=_evidence(function.file, function.line, function.signature),
                build_context=build_context_by_file.get(function.file),
                metadata={"semantic": True},
            )

    for call in semantic.calls:
        caller = (
            semantic_functions_by_name_file.get((call.caller, call.file))
            or function_defs_by_name.get(call.caller)
            or semantic_functions_by_name.get(call.caller)
            or graph.add_node(
                NodeType.FUNCTION,
                call.caller,
                path=call.file,
                metadata={"semantic": True},
            )
        )
        callee = (
            function_defs_by_name.get(call.callee)
            or semantic_functions_by_name.get(call.callee)
            or graph.add_node(
                NodeType.FUNCTION,
                call.callee,
                metadata={"semantic": True},
            )
        )
        graph.add_edge(
            caller,
            callee,
            EdgeType.CALLS,
            extraction_tool="clang-ast",
            confidence=Confidence.CONFIRMED,
            evidence=_evidence(call.file, call.line, _snippet(root, call.file, call.line)),
            build_context=build_context_by_file.get(call.file),
            metadata={
                "caller": call.caller,
                "callee": call.callee,
                "semantic": True,
            },
        )


def build_canonical_graph(
    root: str | Path,
    indexes: CoreIndexes | None = None,
    *,
    semantic: bool = False,
    semantic_limit: int | None = None,
    outline_source: str = "regex",
    symbol_source: str = "outline",
) -> Graph:
    root_path = Path(root).resolve()
    indexes = indexes or build_indexes(
        root_path,
        outline_source=outline_source,
        symbol_source=symbol_source,
    )
    graph = Graph()

    repo_node = graph.add_node(
        NodeType.REPOSITORY,
        root_path.name,
        path=root_path.as_posix(),
        metadata={
            "language_counts": indexes.manifest.language_counts,
            "top_level_modules": indexes.manifest.top_level_modules,
        },
        node_id=stable_id("repo", root_path.as_posix()),
    )

    module_nodes: dict[str, Node] = {}
    for module in indexes.manifest.top_level_modules:
        module_node = graph.add_node(
            NodeType.MODULE,
            module,
            path=module,
            metadata={"top_level": True},
        )
        module_nodes[module] = module_node
        graph.add_edge(
            repo_node,
            module_node,
            EdgeType.CONTAINS,
            extraction_tool="repository-intake",
            confidence=Confidence.CONFIRMED,
        )

    dir_nodes: dict[str, Node] = {}
    for directory in indexes.manifest.directories:
        node = graph.add_node(
            NodeType.DIRECTORY,
            directory.path,
            path=directory.path,
            metadata={"depth": directory.depth},
        )
        dir_nodes[directory.path] = node

    file_nodes: dict[str, Node] = {}
    documentation_by_file = indexes.documentation.by_file()
    for file_record in indexes.manifest.files:
        metadata = {
            "language": file_record.language,
            "kind": file_record.kind,
            "size": file_record.size,
            "generated_candidate": file_record.generated_candidate,
        }
        doc_snippets = documentation_by_file.get(file_record.path)
        if doc_snippets:
            metadata["documentation_snippets"] = [snippet.to_dict() for snippet in doc_snippets]
        node = graph.add_node(
            _node_type_for_file(file_record.kind),
            Path(file_record.path).name,
            path=file_record.path,
            metadata=metadata,
        )
        file_nodes[file_record.path] = node

    _add_contains_edges(graph, repo_node, dir_nodes, file_nodes)

    for file_path, file_node in file_nodes.items():
        top = Path(file_path).parts[0] if Path(file_path).parts else file_path
        module_node = module_nodes.get(top)
        if module_node and module_node.id != file_node.id:
            graph.add_edge(
                module_node,
                file_node,
                EdgeType.CONTAINS,
                extraction_tool="repository-intake",
                confidence=Confidence.LIKELY,
            )

    symbol_nodes: dict[tuple[str, str, int], Node] = {}
    function_defs_by_name: dict[str, Node] = {}
    build_context_by_file = {
        command.file: command.file
        for command in indexes.build_context.translation_units
    }
    for symbol in indexes.symbols.symbols:
        node = graph.add_node(
            _node_type_for_symbol(symbol),
            symbol.name,
            path=symbol.file,
            metadata={
                "kind": symbol.kind,
                "line": symbol.line,
                "scope": symbol.scope,
                "declaration": symbol.declaration,
                "definition": symbol.definition,
                "signature": symbol.signature,
            },
            node_id=_symbol_node_id(symbol),
        )
        symbol_nodes[(symbol.name, symbol.file, symbol.line)] = node
        file_node = file_nodes.get(symbol.file)
        if file_node:
            graph.add_edge(
                file_node,
                node,
                EdgeType.DEFINES if symbol.definition else EdgeType.DECLARES,
                extraction_tool=symbol.extraction_tool,
                evidence=_evidence(symbol.file, symbol.line, symbol.signature),
                confidence=Confidence.CONFIRMED if symbol.definition else Confidence.LIKELY,
                build_context=build_context_by_file.get(symbol.file),
            )
        if symbol.kind == "Function" and symbol.definition:
            function_defs_by_name.setdefault(symbol.name, node)
            function_defs_by_name.setdefault(symbol.name.rsplit("::", 1)[-1], node)

    for include in indexes.includes.includes:
        source = file_nodes.get(include.source)
        if not source:
            continue
        if include.resolved:
            target = file_nodes.get(include.resolved)
        else:
            target = graph.add_node(
                NodeType.HEADER_FILE,
                include.include,
                path=f"<{include.include}>" if include.system else include.include,
                metadata={"external": include.system, "resolved": False},
            )
        if not target:
            continue
        graph.add_edge(
            source,
            target,
            EdgeType.INCLUDES,
            extraction_tool="include-regex",
            evidence=_evidence(include.source, include.line, f"#include {include.include}"),
            confidence=Confidence.CONFIRMED if include.resolved else Confidence.POSSIBLE,
            build_context=build_context_by_file.get(include.source),
            metadata={"system": include.system, "include": include.include},
        )
        if include.resolved:
            source_module = module_nodes.get(_top_level(include.source) or "")
            target_module = module_nodes.get(_top_level(include.resolved) or "")
            if source_module and target_module and source_module.id != target_module.id:
                graph.add_edge(
                    source_module,
                    target_module,
                    EdgeType.DEPENDS_ON,
                    extraction_tool="include-regex",
                    confidence=Confidence.LIKELY,
                    evidence=_evidence(include.source, include.line, f"#include {include.include}"),
                    build_context=build_context_by_file.get(include.source),
                    metadata={
                        "basis": "resolved include",
                        "source_file": include.source,
                        "target_file": include.resolved,
                    },
                )

    include_evidence_by_directory_dependency = {}
    for include in indexes.includes.includes:
        if not include.resolved:
            continue
        dependency_key = (_directory(include.source), _directory(include.resolved))
        include_evidence_by_directory_dependency.setdefault(
            dependency_key,
            _evidence(include.source, include.line, f"#include {include.include}"),
        )

    for source_dir, target_dirs in indexes.includes.directory_dependencies.items():
        source_node = dir_nodes.get(source_dir)
        for target_dir in target_dirs:
            target_node = dir_nodes.get(target_dir)
            if source_node and target_node and source_node.id != target_node.id:
                evidence = include_evidence_by_directory_dependency.get((source_dir, target_dir))
                graph.add_edge(
                    source_node,
                    target_node,
                    EdgeType.DEPENDS_ON,
                    extraction_tool="include-regex",
                    confidence=Confidence.LIKELY,
                    evidence=evidence,
                )

    for command in indexes.build_context.translation_units:
        source_file = file_nodes.get(command.file)
        tu_node = graph.add_node(
            NodeType.TRANSLATION_UNIT,
            command.file,
            path=command.file,
            metadata={
                "directory": command.directory,
                "arguments": command.arguments,
                "include_paths": command.include_paths,
                "macros": command.macros,
                "target_arch": command.target_arch,
            },
        )
        if source_file:
            graph.add_edge(
                source_file,
                tu_node,
                EdgeType.COMPILED_IN,
                extraction_tool="compile-commands",
                confidence=Confidence.CONFIRMED,
                build_context=command.file,
            )
        for include_path in command.include_paths:
            flag_node = graph.add_node(
                NodeType.COMPILER_FLAG,
                f"-I{include_path}",
                metadata={"kind": "include_path", "value": include_path},
            )
            graph.add_edge(
                tu_node,
                flag_node,
                EdgeType.COMPILED_IN,
                extraction_tool="compile-commands",
                confidence=Confidence.CONFIRMED,
                build_context=command.file,
            )
        for macro in command.macros:
            feature_node = graph.add_node(
                NodeType.FEATURE_FLAG,
                macro,
                metadata=_macro_metadata(macro),
            )
            graph.add_edge(
                tu_node,
                feature_node,
                EdgeType.COMPILED_IN,
                extraction_tool="compile-commands",
                confidence=Confidence.CONFIRMED,
                build_context=command.file,
            )
        if command.target_arch:
            arch_node = graph.add_node(
                NodeType.ARCHITECTURE,
                command.target_arch,
                metadata={"target_arch": command.target_arch, "source": "compile_commands"},
            )
            graph.add_edge(
                tu_node,
                arch_node,
                EdgeType.COMPILED_IN,
                extraction_tool="compile-commands",
                confidence=Confidence.CONFIRMED,
                build_context=command.file,
                architecture_context=command.target_arch,
            )

    for call in indexes.call_graph.calls:
        caller = function_defs_by_name.get(call.caller)
        if not caller:
            caller = graph.add_node(
                NodeType.FUNCTION,
                call.caller,
                path=call.caller_file,
                metadata={"line": call.caller_line, "definition": True},
            )
        if call.resolved:
            target = function_defs_by_name.get(call.callee) or graph.add_node(
                NodeType.FUNCTION,
                call.callee,
                path=call.callee_file,
                metadata={"definition": True},
            )
            edge_type = EdgeType.CALLS
        else:
            target = graph.add_node(
                NodeType.SYMBOL,
                call.callee,
                path=call.caller_file,
                metadata={"unresolved": True},
            )
            edge_type = EdgeType.UNRESOLVED
        graph.add_edge(
            caller,
            target,
            edge_type,
            extraction_tool="callgraph-regex",
            confidence=call.confidence,
            evidence=_evidence(call.caller_file, call.line, call.snippet),
            build_context=build_context_by_file.get(call.caller_file),
            metadata={
                "caller": call.caller,
                "callee": call.callee,
                "resolved": call.resolved,
            },
        )

    for match in indexes.architecture.matches:
        file_node = file_nodes.get(match.file)
        arch_node = graph.add_node(
            NodeType.ARCHITECTURE,
            match.architecture,
            metadata={"architecture": match.architecture},
        )
        if file_node:
            graph.add_edge(
                file_node,
                arch_node,
                EdgeType.ARCH_SPECIFIC,
                extraction_tool="architecture-classifier",
                confidence=match.confidence,
                evidence=_evidence(match.file, match.line, match.snippet),
                build_context=build_context_by_file.get(match.file),
                architecture_context=match.architecture,
                metadata={"reason": match.reason},
            )

    for symbol in indexes.symbols.symbols:
        if not symbol.file.endswith((".h", ".hh", ".hpp", ".hxx")):
            continue
        if symbol.kind != "Function":
            continue
        api_node = graph.add_node(
            NodeType.PUBLIC_API,
            symbol.name,
            path=symbol.file,
            metadata={"line": symbol.line, "signature": symbol.signature},
        )
        symbol_node = symbol_nodes.get((symbol.name, symbol.file, symbol.line))
        if symbol_node:
            graph.add_edge(
                api_node,
                symbol_node,
                EdgeType.EXPORTED_BY,
                extraction_tool="symbol-index",
                evidence=_evidence(symbol.file, symbol.line, symbol.signature),
                confidence=Confidence.LIKELY,
            )

    if semantic:
        semantic_index = build_clang_semantic_index(root_path, limit=semantic_limit)
        repo_node.metadata["semantic"] = {
            "enabled": True,
            "available": semantic_index.available,
            "diagnostics": semantic_index.diagnostics,
            "function_count": len(semantic_index.functions),
            "call_count": len(semantic_index.calls),
        }
        _add_semantic_calls(
            graph,
            semantic_index,
            root_path,
            function_defs_by_name,
            file_nodes,
            build_context_by_file,
        )

    return graph
