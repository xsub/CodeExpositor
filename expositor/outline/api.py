"""Fast C/C++ outline extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from expositor._util import (
    code_line,
    is_c_cpp,
    iter_repo_files,
    line_number_for_offset,
    posix_relpath,
    read_text,
    strip_comments_preserve_lines,
)


CONTROL_WORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "sizeof",
    "defined",
}

MACRO_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+(?P<name>[A-Za-z_]\w*)", re.MULTILINE)
STRUCT_RE = re.compile(r"\b(?P<kind>struct|class)[ \t]+(?P<name>[A-Za-z_]\w*)")
ENUM_RE = re.compile(r"\benum(?:[ \t]+class)?[ \t]+(?P<name>[A-Za-z_]\w*)")
TYPEDEF_RE = re.compile(r"^[ \t]*typedef\b.*?\b(?P<name>[A-Za-z_]\w*)[ \t]*;", re.MULTILINE)
FUNC_DEF_RE = re.compile(
    r"(?m)^[ \t]*(?P<signature>"
    r"(?:[A-Za-z_][\w:<>\s*&~,\[\]]+[ \t]+)?"
    r"(?P<name>(?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)"
    r"[ \t]*\([^;{}]*\)[ \t]*(?:const[ \t]*)?)\{"
)
FUNC_DECL_RE = re.compile(
    r"(?m)^[ \t]*(?P<signature>"
    r"(?:extern[ \t]+|static[ \t]+|inline[ \t]+|virtual[ \t]+)?"
    r"(?:[A-Za-z_][\w:<>\s*&~,\[\]]+[ \t]+)"
    r"(?P<name>(?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)"
    r"[ \t]*\([^{};]*\)[ \t]*(?:const[ \t]*)?);"
)
COMMENT_RE = re.compile(r"^\s*(?://|/\*|\*)\s?(?P<text>.*)$")


@dataclass(frozen=True)
class OutlineItem:
    kind: str
    name: str
    file: str
    line: int
    column: int | None = None
    end_line: int | None = None
    signature: str | None = None
    scope: str | None = None
    is_definition: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "signature": self.signature,
            "scope": self.scope,
            "is_definition": self.is_definition,
            "metadata": dict(self.metadata),
        }


@dataclass
class FileOutline:
    path: str
    items: list[OutlineItem] = field(default_factory=list)
    summary_signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "items": [item.to_dict() for item in self.items],
            "summary_signals": self.summary_signals,
        }


@dataclass
class OutlineIndex:
    files: list[FileOutline]
    source: str = "outline-regex"
    diagnostics: list[str] = field(default_factory=list)

    @property
    def items(self) -> list[OutlineItem]:
        return [item for file_outline in self.files for item in file_outline.items]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "diagnostics": list(self.diagnostics),
            "files": [item.to_dict() for item in self.files],
        }


def _scope_for(name: str) -> str | None:
    if "::" not in name:
        return None
    return name.rsplit("::", 1)[0]


def _comment_signals(text: str) -> list[str]:
    signals: list[str] = []
    for line in text.splitlines()[:80]:
        match = COMMENT_RE.match(line)
        if not match:
            if line.strip():
                break
            continue
        value = match.group("text").strip(" */")
        if value:
            signals.append(value)
        if len(signals) >= 5:
            break
    return signals


def _function_end_line(text: str, brace_offset: int) -> int:
    depth = 0
    for index in range(brace_offset, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return line_number_for_offset(text, index)
    return line_number_for_offset(text, len(text))


def extract_file_outline(root: Path, path: Path) -> FileOutline:
    relpath = posix_relpath(path, root)
    text = read_text(path)
    code = strip_comments_preserve_lines(text)
    items: list[OutlineItem] = []

    for match in MACRO_RE.finditer(code):
        line = line_number_for_offset(code, match.start())
        items.append(
            OutlineItem(
                kind="macro",
                name=match.group("name"),
                file=relpath,
                line=line,
                column=match.start("name") - code.rfind("\n", 0, match.start("name")),
                is_definition=True,
                signature=code_line(text, line),
            )
        )

    for regex, kind in ((STRUCT_RE, "struct"), (ENUM_RE, "enum")):
        for match in regex.finditer(code):
            line = line_number_for_offset(code, match.start())
            items.append(
                OutlineItem(
                    kind=kind if kind == "enum" else match.group("kind"),
                    name=match.group("name"),
                    file=relpath,
                    line=line,
                    column=match.start("name") - code.rfind("\n", 0, match.start("name")),
                    is_definition="{" in code[match.end() : match.end() + 80],
                    signature=code_line(text, line),
                )
            )

    for match in TYPEDEF_RE.finditer(code):
        line = line_number_for_offset(code, match.start())
        items.append(
            OutlineItem(
                kind="typedef",
                name=match.group("name"),
                file=relpath,
                line=line,
                column=match.start("name") - code.rfind("\n", 0, match.start("name")),
                is_definition=True,
                signature=code_line(text, line),
            )
        )

    for match in FUNC_DEF_RE.finditer(code):
        name = match.group("name")
        if name in CONTROL_WORDS:
            continue
        line = line_number_for_offset(code, match.start())
        if code_line(text, line).lstrip().startswith("return "):
            continue
        items.append(
            OutlineItem(
                kind="function",
                name=name,
                file=relpath,
                line=line,
                column=match.start("name") - code.rfind("\n", 0, match.start("name")),
                end_line=_function_end_line(code, match.end() - 1),
                signature=" ".join(match.group("signature").split()),
                scope=_scope_for(name),
                is_definition=True,
            )
        )

    for match in FUNC_DECL_RE.finditer(code):
        name = match.group("name")
        if name in CONTROL_WORDS:
            continue
        line = line_number_for_offset(code, match.start())
        if code_line(text, line).lstrip().startswith("return "):
            continue
        items.append(
            OutlineItem(
                kind="function",
                name=name,
                file=relpath,
                line=line,
                column=match.start("name") - code.rfind("\n", 0, match.start("name")),
                signature=" ".join(match.group("signature").split()),
                scope=_scope_for(name),
                is_definition=False,
            )
        )

    items.sort(key=lambda item: (item.line, item.kind, item.name))
    return FileOutline(
        path=relpath,
        items=items,
        summary_signals={
            "comment_signals": _comment_signals(text),
            "item_count": len(items),
        },
    )


def _regex_outline_index(
    root: str | Path,
    *,
    diagnostics: list[str] | None = None,
) -> OutlineIndex:
    root_path = Path(root).resolve()
    files = [
        extract_file_outline(root_path, path)
        for path in iter_repo_files(root_path)
        if is_c_cpp(path)
    ]
    return OutlineIndex(
        files=files,
        source="outline-regex",
        diagnostics=list(diagnostics or []),
    )


def build_outline(root: str | Path, *, source: str = "regex") -> OutlineIndex:
    if source == "regex":
        return _regex_outline_index(root)
    if source == "tree-sitter":
        from expositor.outline.tree_sitter import build_tree_sitter_outline

        return build_tree_sitter_outline(root)
    if source == "auto":
        from expositor.outline.tree_sitter import build_tree_sitter_outline

        tree_sitter_index = build_tree_sitter_outline(root)
        if tree_sitter_index.items:
            return tree_sitter_index
        diagnostics = list(tree_sitter_index.diagnostics)
        diagnostics.append("tree-sitter unavailable or empty; used outline-regex fallback")
        return _regex_outline_index(root, diagnostics=diagnostics)
    raise ValueError(source)
