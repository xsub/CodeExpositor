"""Repository intake API."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from expositor._util import (
    BUILD_FILE_NAMES,
    classify_language,
    detect_generated,
    is_c_cpp,
    is_documentation,
    is_header,
    is_source,
    iter_repo_files,
    posix_relpath,
    read_text,
)


@dataclass(frozen=True)
class FileRecord:
    path: str
    language: str
    kind: str
    size: int
    generated_candidate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "kind": self.kind,
            "size": self.size,
            "generated_candidate": self.generated_candidate,
        }


@dataclass(frozen=True)
class DirectoryRecord:
    path: str
    depth: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "depth": self.depth}


@dataclass
class RepositoryManifest:
    root: str
    files: list[FileRecord] = field(default_factory=list)
    directories: list[DirectoryRecord] = field(default_factory=list)
    language_counts: dict[str, int] = field(default_factory=dict)
    top_level_modules: list[str] = field(default_factory=list)
    build_files: list[str] = field(default_factory=list)
    generated_candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": [item.to_dict() for item in self.files],
            "directories": [item.to_dict() for item in self.directories],
            "language_counts": dict(sorted(self.language_counts.items())),
            "top_level_modules": self.top_level_modules,
            "build_files": self.build_files,
            "generated_candidates": self.generated_candidates,
        }


def file_kind(path: Path) -> str:
    if is_source(path):
        return "source"
    if is_header(path):
        return "header"
    if is_documentation(path):
        return "documentation"
    if path.name in BUILD_FILE_NAMES:
        return "build"
    return "other"


def scan_repository(root: str | Path) -> RepositoryManifest:
    """Scan a repository and return deterministic inventory metadata."""

    root_path = Path(root).resolve()
    if not root_path.exists():
        raise FileNotFoundError(root_path)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    files: list[FileRecord] = []
    directories: set[str] = set()
    languages: Counter[str] = Counter()
    build_files: list[str] = []
    generated_candidates: list[str] = []
    top_level_modules: set[str] = set()

    for path in iter_repo_files(root_path):
        relpath = posix_relpath(path, root_path)
        parts = Path(relpath).parts
        if len(parts) > 1:
            top_level_modules.add(parts[0])
        elif is_c_cpp(path):
            top_level_modules.add(Path(relpath).stem)

        for index in range(1, len(parts)):
            directories.add(Path(*parts[:index]).as_posix())

        language = classify_language(path)
        kind = file_kind(path)
        languages[language] += 1

        generated = False
        if is_c_cpp(path):
            generated = detect_generated(read_text(path))
            if generated:
                generated_candidates.append(relpath)

        if path.name in BUILD_FILE_NAMES:
            build_files.append(relpath)

        files.append(
            FileRecord(
                path=relpath,
                language=language,
                kind=kind,
                size=path.stat().st_size,
                generated_candidate=generated,
            )
        )

    directory_records = [
        DirectoryRecord(path=directory, depth=len(Path(directory).parts))
        for directory in sorted(directories)
    ]

    return RepositoryManifest(
        root=root_path.as_posix(),
        files=sorted(files, key=lambda item: item.path),
        directories=directory_records,
        language_counts=dict(languages),
        top_level_modules=sorted(top_level_modules),
        build_files=sorted(build_files),
        generated_candidates=sorted(generated_candidates),
    )
