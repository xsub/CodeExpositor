"""Architecture-specific source classifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from expositor._util import is_c_cpp, iter_repo_files, line_number_for_offset, posix_relpath, read_text
from expositor.model import Confidence


ARCH_PARTS = {
    "x86": {"x86", "x86_64", "i386", "i686", "amd64", "sse", "sse2", "avx", "avx2"},
    "arm": {"arm", "armv7", "neon"},
    "aarch64": {"aarch64", "arm64"},
    "riscv": {"riscv", "riscv64"},
    "mips": {"mips", "mips64"},
    "ppc": {"ppc", "ppc64", "powerpc"},
    "wasm": {"wasm", "wasm32", "wasm64"},
}

ARCH_MACROS = {
    "x86": re.compile(r"\b(__i386__|__x86_64__|_M_IX86|_M_X64)\b"),
    "arm": re.compile(r"\b(__arm__|_M_ARM|__ARM_NEON)\b"),
    "aarch64": re.compile(r"\b(__aarch64__|_M_ARM64)\b"),
    "riscv": re.compile(r"\b(__riscv|__riscv_xlen)\b"),
    "mips": re.compile(r"\b(__mips__|__mips64)\b"),
    "ppc": re.compile(r"\b(__powerpc__|__ppc__|__PPC64__)\b"),
    "wasm": re.compile(r"\b(__wasm__|__wasm32__|__wasm64__)\b"),
}


@dataclass(frozen=True)
class ArchitectureMatch:
    file: str
    architecture: str
    confidence: str
    reason: str
    line: int | None = None
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "architecture": self.architecture,
            "confidence": self.confidence,
            "reason": self.reason,
            "line": self.line,
            "snippet": self.snippet,
        }


@dataclass
class ArchitectureIndex:
    matches: list[ArchitectureMatch] = field(default_factory=list)

    def for_arch(self, arch: str) -> list[ArchitectureMatch]:
        return [item for item in self.matches if item.architecture == arch]

    def to_dict(self) -> dict[str, Any]:
        return {"matches": [item.to_dict() for item in self.matches]}


def _path_arches(relpath: str) -> list[tuple[str, str]]:
    lowered_parts = {part.lower() for part in Path(relpath).parts}
    matches: list[tuple[str, str]] = []
    for arch, parts in ARCH_PARTS.items():
        intersection = lowered_parts & parts
        if intersection:
            matches.append((arch, f"path component {sorted(intersection)[0]}"))
    return matches


def classify_architecture(root: str | Path) -> ArchitectureIndex:
    root_path = Path(root).resolve()
    matches: list[ArchitectureMatch] = []

    for path in iter_repo_files(root_path):
        if not is_c_cpp(path):
            continue
        relpath = posix_relpath(path, root_path)
        seen: set[tuple[str, int | None, str]] = set()
        for arch, reason in _path_arches(relpath):
            key = (arch, None, reason)
            if key not in seen:
                matches.append(
                    ArchitectureMatch(
                        file=relpath,
                        architecture=arch,
                        confidence=Confidence.LIKELY.value,
                        reason=reason,
                    )
                )
                seen.add(key)

        text = read_text(path)
        for arch, regex in ARCH_MACROS.items():
            for match in regex.finditer(text):
                line = line_number_for_offset(text, match.start())
                snippet = text.splitlines()[line - 1].strip()
                key = (arch, line, snippet)
                if key in seen:
                    continue
                matches.append(
                    ArchitectureMatch(
                        file=relpath,
                        architecture=arch,
                        confidence=Confidence.CONFIRMED.value,
                        reason=f"architecture macro {match.group(0)}",
                        line=line,
                        snippet=snippet,
                    )
                )
                seen.add(key)

    matches.sort(key=lambda item: (item.file, item.architecture, item.line or 0, item.reason))
    return ArchitectureIndex(matches=matches)
