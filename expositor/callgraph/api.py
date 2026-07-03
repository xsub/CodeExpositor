"""Direct-call graph baseline for C/C++ code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from expositor._util import is_c_cpp, iter_repo_files, line_number_for_offset, posix_relpath, read_text, strip_comments_preserve_lines
from expositor.model import Confidence
from expositor.outline.api import CONTROL_WORDS, FUNC_DEF_RE
from expositor.symbols import SymbolIndex, build_symbol_index


CALL_RE = re.compile(r"\b(?P<name>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)[ \t]*\(")

EXCLUDED_CALL_NAMES = CONTROL_WORDS | {
    "static_cast",
    "reinterpret_cast",
    "const_cast",
    "dynamic_cast",
}


@dataclass(frozen=True)
class FunctionBody:
    name: str
    file: str
    line: int
    end_line: int
    body_start: int
    body_end: int


@dataclass(frozen=True)
class CallRecord:
    caller: str
    caller_file: str
    caller_line: int
    callee: str
    line: int
    resolved: bool
    confidence: str
    callee_file: str | None = None
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "caller_file": self.caller_file,
            "caller_line": self.caller_line,
            "callee": self.callee,
            "callee_file": self.callee_file,
            "line": self.line,
            "resolved": self.resolved,
            "confidence": self.confidence,
            "snippet": self.snippet,
        }


@dataclass
class DirectCallGraph:
    calls: list[CallRecord] = field(default_factory=list)

    def callers_of(self, function: str) -> list[CallRecord]:
        return [
            item
            for item in self.calls
            if item.callee == function or item.callee.endswith(f"::{function}")
        ]

    def callees_of(self, function: str) -> list[CallRecord]:
        return [
            item
            for item in self.calls
            if item.caller == function or item.caller.endswith(f"::{function}")
        ]

    def to_dict(self) -> dict[str, Any]:
        return {"calls": [item.to_dict() for item in self.calls]}


def _find_matching_brace(text: str, brace_offset: int) -> int:
    depth = 0
    for index in range(brace_offset, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(text) - 1


def _function_bodies(root: Path, path: Path) -> list[FunctionBody]:
    relpath = posix_relpath(path, root)
    text = read_text(path)
    code = strip_comments_preserve_lines(text)
    bodies: list[FunctionBody] = []
    for match in FUNC_DEF_RE.finditer(code):
        name = match.group("name")
        if name in CONTROL_WORDS:
            continue
        brace_offset = match.end() - 1
        end_offset = _find_matching_brace(code, brace_offset)
        bodies.append(
            FunctionBody(
                name=name,
                file=relpath,
                line=line_number_for_offset(code, match.start()),
                end_line=line_number_for_offset(code, end_offset),
                body_start=brace_offset + 1,
                body_end=end_offset,
            )
        )
    return bodies


def _function_symbols(symbols: SymbolIndex) -> dict[str, tuple[str, str]]:
    targets: dict[str, tuple[str, str]] = {}
    for symbol in symbols.symbols:
        if symbol.kind not in {"Function", "Method"} and symbol.kind != "Function":
            continue
        if not symbol.definition:
            continue
        targets.setdefault(symbol.name, (symbol.name, symbol.file))
        targets.setdefault(symbol.name.rsplit("::", 1)[-1], (symbol.name, symbol.file))
    return targets


def _line_snippet(text: str, line: int) -> str:
    lines = text.splitlines()
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()
    return ""


def build_call_graph(root: str | Path, symbols: SymbolIndex | None = None) -> DirectCallGraph:
    root_path = Path(root).resolve()
    symbols = symbols or build_symbol_index(root_path)
    targets = _function_symbols(symbols)
    calls: list[CallRecord] = []

    for path in iter_repo_files(root_path):
        if not is_c_cpp(path):
            continue
        relpath = posix_relpath(path, root_path)
        text = read_text(path)
        code = strip_comments_preserve_lines(text)
        bodies = _function_bodies(root_path, path)
        for body in bodies:
            body_text = code[body.body_start : body.body_end]
            seen_at_line: set[tuple[str, int]] = set()
            for match in CALL_RE.finditer(body_text):
                callee_name = match.group("name")
                if callee_name in EXCLUDED_CALL_NAMES:
                    continue
                unqualified = callee_name.rsplit("::", 1)[-1]
                if unqualified in EXCLUDED_CALL_NAMES:
                    continue
                absolute_offset = body.body_start + match.start()
                line = line_number_for_offset(code, absolute_offset)
                key = (callee_name, line)
                if key in seen_at_line:
                    continue
                seen_at_line.add(key)
                resolved = targets.get(callee_name) or targets.get(unqualified)
                if resolved:
                    resolved_name, resolved_file = resolved
                    confidence = Confidence.CONFIRMED.value
                    callee = resolved_name
                    callee_file = resolved_file
                else:
                    confidence = Confidence.UNRESOLVED.value
                    callee = callee_name
                    callee_file = None
                calls.append(
                    CallRecord(
                        caller=body.name,
                        caller_file=relpath,
                        caller_line=body.line,
                        callee=callee,
                        callee_file=callee_file,
                        line=line,
                        resolved=bool(resolved),
                        confidence=confidence,
                        snippet=_line_snippet(text, line),
                    )
                )

    calls.sort(key=lambda item: (item.caller_file, item.caller_line, item.line, item.caller, item.callee))
    return DirectCallGraph(calls=calls)
