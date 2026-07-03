"""Symbol index API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from expositor.outline import build_outline
from expositor.outline.api import OutlineIndex, OutlineItem


SYMBOL_KIND_BY_OUTLINE = {
    "function": "Function",
    "macro": "Macro",
    "struct": "Struct",
    "class": "Class",
    "enum": "Enum",
    "typedef": "Typedef",
}


@dataclass(frozen=True)
class SymbolRecord:
    name: str
    kind: str
    file: str
    line: int
    scope: str | None = None
    declaration: bool = False
    definition: bool = False
    signature: str | None = None
    extraction_tool: str = "outline-regex"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "scope": self.scope,
            "declaration": self.declaration,
            "definition": self.definition,
            "signature": self.signature,
            "extraction_tool": self.extraction_tool,
        }


@dataclass
class SymbolIndex:
    symbols: list[SymbolRecord] = field(default_factory=list)
    source: str = "outline-regex"
    diagnostics: list[str] = field(default_factory=list)

    def by_name(self, name: str) -> list[SymbolRecord]:
        return [item for item in self.symbols if item.name == name or item.name.endswith(f"::{name}")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "diagnostics": list(self.diagnostics),
            "symbols": [item.to_dict() for item in self.symbols],
        }


def symbol_from_outline(item: OutlineItem) -> SymbolRecord | None:
    kind = SYMBOL_KIND_BY_OUTLINE.get(item.kind)
    if not kind:
        return None
    return SymbolRecord(
        name=item.name,
        kind=kind,
        file=item.file,
        line=item.line,
        scope=item.scope,
        declaration=not item.is_definition,
        definition=item.is_definition,
        signature=item.signature,
        extraction_tool=item.metadata.get("adapter", "outline-regex"),
    )


def _outline_symbol_index(
    root: str | Path,
    outline: OutlineIndex | None = None,
    *,
    diagnostics: list[str] | None = None,
) -> SymbolIndex:
    outline = outline or build_outline(root)
    symbols = [
        symbol
        for item in outline.items
        if (symbol := symbol_from_outline(item)) is not None
    ]
    symbols.sort(key=lambda item: (item.file, item.line, item.kind, item.name))
    return SymbolIndex(
        symbols=symbols,
        source="outline-regex",
        diagnostics=list(diagnostics or []),
    )


def build_symbol_index(
    root: str | Path,
    outline: OutlineIndex | None = None,
    *,
    source: str = "outline",
) -> SymbolIndex:
    if source == "outline":
        return _outline_symbol_index(root, outline)
    if source == "ctags":
        from expositor.symbols.ctags import build_ctags_symbol_index

        return build_ctags_symbol_index(root)
    if source == "auto":
        from expositor.symbols.ctags import build_ctags_symbol_index

        ctags_index = build_ctags_symbol_index(root)
        if ctags_index.symbols:
            return ctags_index
        diagnostics = list(ctags_index.diagnostics)
        diagnostics.append("Universal Ctags unavailable or empty; used outline-regex fallback")
        return _outline_symbol_index(root, outline, diagnostics=diagnostics)
    raise ValueError(source)
