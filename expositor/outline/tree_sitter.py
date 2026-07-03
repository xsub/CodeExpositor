"""Optional tree-sitter outline adapter.

tree-sitter is an adapter for fast structural outline. It does not define the
canonical graph schema and it is not the semantic source of truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from expositor._util import code_line, is_c_cpp, iter_repo_files, posix_relpath, read_text
from expositor.outline.api import FileOutline, OutlineIndex, OutlineItem


TREE_SITTER_SOURCE = "tree-sitter"


def tree_sitter_available() -> bool:
    try:
        _parser_for_language("c")
    except RuntimeError:
        return False
    return True


def _language_name(path: Path) -> str:
    return "cpp" if path.suffix.lower() in {".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"} else "c"


def _parser_for_language(language: str) -> Any:
    try:
        from tree_sitter_languages import get_parser  # type: ignore

        return get_parser("cpp" if language == "cpp" else "c")
    except Exception:
        pass

    package_name = "tree_sitter_cpp" if language == "cpp" else "tree_sitter_c"
    try:
        from tree_sitter import Language, Parser  # type: ignore
        grammar = __import__(package_name)
    except Exception as exc:
        raise RuntimeError(f"tree-sitter parser for {language} is unavailable: {exc}") from exc

    try:
        tree_language = Language(grammar.language())
    except Exception:
        tree_language = grammar.language()

    parser = Parser()
    try:
        parser.language = tree_language
    except Exception:
        parser.set_language(tree_language)
    return parser


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _field(node: Any, name: str) -> Any | None:
    try:
        return node.child_by_field_name(name)
    except Exception:
        return None


def _children(node: Any) -> list[Any]:
    return list(getattr(node, "children", []) or [])


def _find_first(node: Any, types: set[str]) -> Any | None:
    if getattr(node, "type", None) in types:
        return node
    for child in _children(node):
        found = _find_first(child, types)
        if found is not None:
            return found
    return None


def _contains(node: Any, node_type: str) -> bool:
    return _find_first(node, {node_type}) is not None


def _line(node: Any) -> int:
    return int(node.start_point[0]) + 1


def _column(node: Any) -> int:
    return int(node.start_point[1]) + 1


def _clean_signature(value: str) -> str:
    return " ".join(value.strip().rstrip(";").split())


def _function_name(declarator: Any | None, source: bytes) -> str | None:
    if declarator is None:
        return None
    name_node = _field(declarator, "name")
    if name_node is not None:
        return _node_text(name_node, source)
    nested = _field(declarator, "declarator")
    if nested is not None and nested is not declarator:
        nested_name = _function_name(nested, source)
        if nested_name:
            return nested_name
    identifier = _find_first(
        declarator,
        {"identifier", "field_identifier", "qualified_identifier", "scoped_identifier", "destructor_name"},
    )
    return _node_text(identifier, source) if identifier is not None else None


def _function_signature(node: Any, source: bytes, *, definition: bool) -> str:
    text = _node_text(node, source)
    if definition and "{" in text:
        text = text.split("{", 1)[0]
    return _clean_signature(text)


def _type_name(node: Any, source: bytes) -> str | None:
    name_node = _field(node, "name")
    if name_node is not None:
        return _node_text(name_node, source)
    identifier = _find_first(node, {"type_identifier", "identifier"})
    return _node_text(identifier, source) if identifier is not None else None


def _macro_item(node: Any, relpath: str, text: str, source: bytes) -> OutlineItem | None:
    name_node = _field(node, "name") or _find_first(node, {"identifier"})
    if name_node is None:
        return None
    line = _line(node)
    return OutlineItem(
        kind="macro",
        name=_node_text(name_node, source),
        file=relpath,
        line=line,
        column=_column(name_node),
        is_definition=True,
        signature=code_line(text, line),
        metadata={"adapter": TREE_SITTER_SOURCE},
    )


def _item_from_node(node: Any, relpath: str, text: str, source: bytes) -> OutlineItem | None:
    node_type = getattr(node, "type", "")
    if node_type in {"preproc_def", "preproc_function_def"}:
        return _macro_item(node, relpath, text, source)

    if node_type == "function_definition":
        declarator = _field(node, "declarator")
        name = _function_name(declarator, source)
        if not name:
            return None
        return OutlineItem(
            kind="function",
            name=name,
            file=relpath,
            line=_line(node),
            column=_column(declarator or node),
            end_line=int(node.end_point[0]) + 1,
            signature=_function_signature(node, source, definition=True),
            is_definition=True,
            metadata={"adapter": TREE_SITTER_SOURCE},
        )

    if node_type == "declaration" and _contains(node, "function_declarator"):
        declarator = _find_first(node, {"function_declarator"})
        name = _function_name(declarator, source)
        if not name:
            return None
        return OutlineItem(
            kind="function",
            name=name,
            file=relpath,
            line=_line(node),
            column=_column(declarator or node),
            signature=_function_signature(node, source, definition=False),
            is_definition=False,
            metadata={"adapter": TREE_SITTER_SOURCE},
        )

    type_kind_by_node = {
        "class_specifier": "class",
        "enum_specifier": "enum",
        "struct_specifier": "struct",
        "type_definition": "typedef",
    }
    if node_type in type_kind_by_node:
        name = _type_name(node, source)
        if not name:
            return None
        line = _line(node)
        return OutlineItem(
            kind=type_kind_by_node[node_type],
            name=name,
            file=relpath,
            line=line,
            column=_column(node),
            is_definition=node_type == "type_definition" or "{" in _node_text(node, source),
            signature=code_line(text, line),
            metadata={"adapter": TREE_SITTER_SOURCE},
        )
    return None


def _walk_outline_nodes(node: Any) -> list[Any]:
    wanted = {
        "class_specifier",
        "declaration",
        "enum_specifier",
        "function_definition",
        "preproc_def",
        "preproc_function_def",
        "struct_specifier",
        "type_definition",
    }
    nodes = []
    if getattr(node, "type", "") in wanted:
        nodes.append(node)
    for child in _children(node):
        nodes.extend(_walk_outline_nodes(child))
    return nodes


def extract_tree_sitter_file_outline(root: Path, path: Path, parser: Any) -> FileOutline:
    relpath = posix_relpath(path, root)
    text = read_text(path)
    source = text.encode("utf-8")
    tree = parser.parse(source)
    items = []
    seen: set[tuple[str, str, str, int, bool]] = set()
    for node in _walk_outline_nodes(tree.root_node):
        item = _item_from_node(node, relpath, text, source)
        if item is None:
            continue
        key = (item.kind, item.name, item.file, item.line, item.is_definition)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    items.sort(key=lambda item: (item.line, item.kind, item.name))
    return FileOutline(
        path=relpath,
        items=items,
        summary_signals={
            "item_count": len(items),
            "adapter": TREE_SITTER_SOURCE,
        },
    )


def build_tree_sitter_outline(root: str | Path) -> OutlineIndex:
    root_path = Path(root).resolve()
    parsers: dict[str, Any] = {}
    failed_languages: set[str] = set()
    diagnostics: list[str] = []
    files: list[FileOutline] = []

    for path in iter_repo_files(root_path):
        if not is_c_cpp(path):
            continue
        language = _language_name(path)
        if language in failed_languages:
            continue
        if language not in parsers:
            try:
                parsers[language] = _parser_for_language(language)
            except RuntimeError as exc:
                diagnostics.append(str(exc))
                failed_languages.add(language)
                continue
        try:
            files.append(extract_tree_sitter_file_outline(root_path, path, parsers[language]))
        except Exception as exc:
            diagnostics.append(f"{posix_relpath(path, root_path)}: tree-sitter parse failed: {exc}")

    return OutlineIndex(
        files=files,
        source=TREE_SITTER_SOURCE,
        diagnostics=diagnostics,
    )
