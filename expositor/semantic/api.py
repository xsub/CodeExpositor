"""Optional Clang AST JSON semantic spike.

This adapter validates the semantic-analysis path without making Clang the
internal graph model. It emits deterministic Code Expositor records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from expositor.build_context import load_build_context
from expositor.model import Confidence


DECL_KINDS = {"FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDestructorDecl"}


@dataclass(frozen=True)
class SemanticFunction:
    name: str
    file: str
    line: int
    kind: str
    definition: bool
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": self.file,
            "line": self.line,
            "kind": self.kind,
            "definition": self.definition,
            "signature": self.signature,
        }


@dataclass(frozen=True)
class SemanticCall:
    caller: str
    callee: str
    file: str
    line: int
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "callee": self.callee,
            "file": self.file,
            "line": self.line,
            "confidence": self.confidence,
        }


@dataclass
class ClangSemanticIndex:
    available: bool
    functions: list[SemanticFunction] = field(default_factory=list)
    calls: list[SemanticCall] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "functions": [item.to_dict() for item in self.functions],
            "calls": [item.to_dict() for item in self.calls],
            "diagnostics": self.diagnostics,
        }


def _sanitize_arguments(args: list[str], source_file: str) -> list[str]:
    sanitized: list[str] = []
    skip_next = False
    source_seen = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if index == 0 and Path(arg).name in {"cc", "gcc", "clang", "c++", "g++", "clang++"}:
            continue
        if arg in {"-c", "-S", "-E"}:
            continue
        if arg in {"-o", "-MF", "-MT", "-MQ"}:
            skip_next = True
            continue
        if arg.startswith("-o") and len(arg) > 2:
            continue
        if arg == source_file or Path(arg).as_posix() == source_file:
            source_seen = True
        sanitized.append(arg)
    if not source_seen:
        sanitized.append(source_file)
    return sanitized


def _relpath_from_loc(loc: dict[str, Any], fallback_file: str, root: Path) -> str:
    file_value = loc.get("file") or loc.get("includedFrom", {}).get("file") or fallback_file
    path = Path(str(file_value))
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _is_repo_file(path: str, root: Path) -> bool:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate.resolve().relative_to(root)
            return True
        except ValueError:
            return False
    return not path.startswith("../") and not path.startswith("/usr/")


def _line_from_loc(loc: dict[str, Any], file: str, root: Path) -> int:
    if loc.get("line"):
        return int(loc["line"])
    if loc.get("offset") is None:
        return 0
    path = Path(file)
    if not path.is_absolute():
        path = root / path
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return text.count("\n", 0, int(loc["offset"])) + 1


def _has_compound_stmt(node: dict[str, Any]) -> bool:
    return any(child.get("kind") == "CompoundStmt" for child in node.get("inner", []) if isinstance(child, dict))


def _called_decl(node: dict[str, Any]) -> str | None:
    referenced = node.get("referencedDecl")
    if isinstance(referenced, dict) and referenced.get("kind") in DECL_KINDS:
        return referenced.get("name")
    member = node.get("referencedMemberDecl")
    if isinstance(member, dict) and member.get("kind") in DECL_KINDS:
        return member.get("name")
    for child in node.get("inner", []) or []:
        if isinstance(child, dict):
            found = _called_decl(child)
            if found:
                return found
    return None


def _walk_ast(
    node: dict[str, Any],
    *,
    root: Path,
    fallback_file: str,
    current_function: str | None,
    functions: dict[tuple[str, str, int], SemanticFunction],
    calls: set[SemanticCall],
) -> None:
    kind = node.get("kind")
    loc = node.get("loc") or node.get("range", {}).get("begin", {})

    if kind in DECL_KINDS and node.get("name") and not node.get("isImplicit"):
        file = _relpath_from_loc(loc, fallback_file, root)
        line = _line_from_loc(loc, file, root)
        if line and _is_repo_file(file, root):
            function = SemanticFunction(
                name=str(node["name"]),
                file=file,
                line=line,
                kind=str(kind),
                definition=_has_compound_stmt(node),
                signature=(node.get("type") or {}).get("qualType"),
            )
            functions.setdefault((function.name, function.file, function.line), function)
            current_function = function.name

    if kind == "CallExpr" and current_function:
        begin = (node.get("range") or {}).get("begin", {})
        file = _relpath_from_loc(begin, fallback_file, root)
        line = _line_from_loc(begin, file, root)
        callee = _called_decl(node)
        if callee and line and _is_repo_file(file, root):
            calls.add(
                SemanticCall(
                    caller=current_function,
                    callee=callee,
                    file=file,
                    line=line,
                    confidence=Confidence.CONFIRMED.value,
                )
            )

    for child in node.get("inner", []) or []:
        if isinstance(child, dict):
            _walk_ast(
                child,
                root=root,
                fallback_file=fallback_file,
                current_function=current_function,
                functions=functions,
                calls=calls,
            )


def build_clang_semantic_index(
    root: str | Path,
    *,
    clang: str = "clang",
    limit: int | None = None,
) -> ClangSemanticIndex:
    root_path = Path(root).resolve()
    clang_path = shutil.which(clang)
    if clang_path is None:
        return ClangSemanticIndex(available=False, diagnostics=[f"{clang} not found"])

    context = load_build_context(root_path)
    if not context.translation_units:
        return ClangSemanticIndex(
            available=True,
            diagnostics=["compile_commands.json not found or contains no translation units"],
        )

    functions: dict[tuple[str, str, int], SemanticFunction] = {}
    calls: set[SemanticCall] = set()
    diagnostics: list[str] = []

    commands = context.translation_units[:limit] if limit else context.translation_units
    for command in commands:
        cwd = root_path / command.directory if command.directory != "." else root_path
        args = _sanitize_arguments(command.arguments, command.file)
        process = subprocess.run(
            [clang_path, "-Xclang", "-ast-dump=json", "-fsyntax-only", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            diagnostics.append(f"{command.file}: clang exited {process.returncode}: {process.stderr.strip()}")
            continue
        try:
            ast = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            diagnostics.append(f"{command.file}: failed to parse clang JSON: {exc}")
            continue
        _walk_ast(
            ast,
            root=root_path,
            fallback_file=command.file,
            current_function=None,
            functions=functions,
            calls=calls,
        )

    return ClangSemanticIndex(
        available=True,
        functions=sorted(functions.values(), key=lambda item: (item.file, item.line, item.name)),
        calls=sorted(calls, key=lambda item: (item.file, item.line, item.caller, item.callee)),
        diagnostics=diagnostics,
    )
