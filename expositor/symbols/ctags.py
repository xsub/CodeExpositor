"""Optional Universal Ctags symbol adapter."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from expositor._util import posix_relpath
from expositor.symbols.api import SymbolIndex, SymbolRecord


CTAGS_KIND_MAP = {
    "class": "Class",
    "enum": "Enum",
    "enumerator": "Symbol",
    "function": "Function",
    "macro": "Macro",
    "member": "Variable",
    "method": "Method",
    "namespace": "Namespace",
    "prototype": "Function",
    "struct": "Struct",
    "typedef": "Typedef",
    "union": "Struct",
    "variable": "Variable",
}

DEFINITION_KINDS = {
    "class",
    "enum",
    "function",
    "macro",
    "method",
    "namespace",
    "struct",
    "typedef",
    "union",
    "variable",
}

DECLARATION_KINDS = {"prototype"}


def universal_ctags_available(executable: str = "ctags") -> bool:
    path = shutil.which(executable)
    if not path:
        return False
    try:
        completed = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    output = f"{completed.stdout}\n{completed.stderr}"
    return completed.returncode == 0 and "Universal Ctags" in output


def _normalise_path(root: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        try:
            return posix_relpath(path.resolve(), root)
        except ValueError:
            return path.as_posix()
    normalised = path.as_posix()
    if normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def _signature(item: dict[str, Any]) -> str | None:
    signature = item.get("signature")
    if signature:
        return str(signature)
    pattern = item.get("pattern")
    if not pattern:
        return None
    value = str(pattern)
    if value.startswith("/^") and value.endswith("$/"):
        value = value[2:-2]
    return value.replace("\\/", "/").strip()


def parse_ctags_json_lines(text: str, root: str | Path = ".") -> list[SymbolRecord]:
    root_path = Path(root).resolve()
    symbols: list[SymbolRecord] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("_type") != "tag":
            continue
        name = item.get("name")
        path = item.get("path")
        kind = str(item.get("kind") or "")
        line_number = item.get("line")
        if not name or not path or kind not in CTAGS_KIND_MAP:
            continue
        if not isinstance(line_number, int) or line_number < 1:
            continue
        symbols.append(
            SymbolRecord(
                name=str(name),
                kind=CTAGS_KIND_MAP[kind],
                file=_normalise_path(root_path, str(path)),
                line=line_number,
                scope=item.get("scope"),
                declaration=kind in DECLARATION_KINDS,
                definition=kind in DEFINITION_KINDS,
                signature=_signature(item),
                extraction_tool="universal-ctags",
            )
        )
    symbols.sort(key=lambda item: (item.file, item.line, item.kind, item.name))
    return symbols


def build_ctags_symbol_index(
    root: str | Path,
    *,
    executable: str = "ctags",
    timeout: int = 60,
) -> SymbolIndex:
    root_path = Path(root).resolve()
    path = shutil.which(executable)
    if not path:
        return SymbolIndex(
            source="universal-ctags",
            diagnostics=[f"{executable} executable not found"],
        )
    if not universal_ctags_available(path):
        return SymbolIndex(
            source="universal-ctags",
            diagnostics=[f"{executable} is not Universal Ctags"],
        )

    command = [
        path,
        "--output-format=json",
        "--fields=+nKSs",
        "--languages=C,C++",
        "--kinds-C=+p",
        "--kinds-C++=+p",
        "-R",
        ".",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root_path,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return SymbolIndex(
            source="universal-ctags",
            diagnostics=[f"Universal Ctags failed: {exc}"],
        )

    diagnostics = []
    if completed.stderr.strip():
        diagnostics.append(completed.stderr.strip())
    if completed.returncode != 0:
        diagnostics.append(f"Universal Ctags exited with status {completed.returncode}")
        return SymbolIndex(source="universal-ctags", diagnostics=diagnostics)

    return SymbolIndex(
        symbols=parse_ctags_json_lines(completed.stdout, root_path),
        source="universal-ctags",
        diagnostics=diagnostics,
    )
