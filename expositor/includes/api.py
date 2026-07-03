"""C/C++ include graph extraction."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from expositor._util import is_c_cpp, iter_repo_files, line_number_for_offset, posix_relpath, read_text


INCLUDE_RE = re.compile(r"^[ \t]*#[ \t]*include[ \t]+(?P<delim>[<\"])(?P<target>[^>\"]+)[>\"]", re.MULTILINE)


@dataclass(frozen=True)
class IncludeRecord:
    source: str
    include: str
    line: int
    system: bool
    resolved: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "include": self.include,
            "line": self.line,
            "system": self.system,
            "resolved": self.resolved,
        }


@dataclass
class IncludeGraph:
    includes: list[IncludeRecord] = field(default_factory=list)
    directory_dependencies: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "includes": [item.to_dict() for item in self.includes],
            "directory_dependencies": {
                key: value for key, value in sorted(self.directory_dependencies.items())
            },
        }


def _file_index(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for path in iter_repo_files(root):
        if is_c_cpp(path):
            index[path.name].append(path)
    return {key: sorted(value) for key, value in index.items()}


def _resolve_include(root: Path, source: Path, include: str, files_by_name: dict[str, list[Path]]) -> str | None:
    candidates = [
        source.parent / include,
        root / include,
        root / "include" / include,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return posix_relpath(candidate.resolve(), root)

    basename_matches = files_by_name.get(Path(include).name, [])
    for match in basename_matches:
        if match.as_posix().endswith(include):
            return posix_relpath(match.resolve(), root)
    if basename_matches:
        return posix_relpath(basename_matches[0].resolve(), root)
    return None


def _directory(path: str) -> str:
    parent = Path(path).parent.as_posix()
    return "." if parent == "." else parent


def build_include_graph(root: str | Path) -> IncludeGraph:
    root_path = Path(root).resolve()
    files_by_name = _file_index(root_path)
    includes: list[IncludeRecord] = []
    directory_dependencies: dict[str, set[str]] = defaultdict(set)

    for path in iter_repo_files(root_path):
        if not is_c_cpp(path):
            continue
        relpath = posix_relpath(path, root_path)
        text = read_text(path)
        for match in INCLUDE_RE.finditer(text):
            include = match.group("target")
            system = match.group("delim") == "<"
            resolved = None if system else _resolve_include(root_path, path, include, files_by_name)
            line = line_number_for_offset(text, match.start())
            includes.append(
                IncludeRecord(
                    source=relpath,
                    include=include,
                    line=line,
                    system=system,
                    resolved=resolved,
                )
            )
            if resolved:
                directory_dependencies[_directory(relpath)].add(_directory(resolved))

    includes.sort(key=lambda item: (item.source, item.line, item.include))
    return IncludeGraph(
        includes=includes,
        directory_dependencies={
            key: sorted(value)
            for key, value in sorted(directory_dependencies.items())
        },
    )
