"""Extract deterministic README/docs snippets for evidence-bound summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from expositor._util import is_documentation, iter_repo_files, posix_relpath, read_text


HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
RST_HEADING_UNDERLINE = {"=", "-", "~", "^"}


@dataclass(frozen=True)
class DocumentationSnippet:
    file: str
    line: int
    heading: str | None
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "heading": self.heading,
            "text": self.text,
        }


@dataclass
class DocumentationIndex:
    snippets: list[DocumentationSnippet] = field(default_factory=list)

    def by_file(self) -> dict[str, list[DocumentationSnippet]]:
        grouped: dict[str, list[DocumentationSnippet]] = {}
        for snippet in self.snippets:
            grouped.setdefault(snippet.file, []).append(snippet)
        return grouped

    def to_dict(self) -> dict[str, Any]:
        return {"snippets": [item.to_dict() for item in self.snippets]}


def _clean_line(line: str) -> str:
    return line.strip().strip("*").strip()


def _compact(text: str, limit: int = 320) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3].rstrip() + "..."


def _paragraph_after(lines: list[str], start: int) -> tuple[int, str] | None:
    paragraph: list[str] = []
    paragraph_start = 0
    for index in range(start, len(lines)):
        line = lines[index].strip()
        if not line:
            if paragraph:
                break
            continue
        if HEADING_RE.match(line):
            if paragraph:
                break
            continue
        if set(line) <= RST_HEADING_UNDERLINE and line:
            continue
        if not paragraph:
            paragraph_start = index + 1
        paragraph.append(_clean_line(line))
        if len(" ".join(paragraph)) >= 320:
            break
    if not paragraph:
        return None
    return paragraph_start, _compact(" ".join(paragraph))


def _rst_heading(lines: list[str], index: int) -> str | None:
    if index + 1 >= len(lines):
        return None
    title = lines[index].strip()
    underline = lines[index + 1].strip()
    if not title or not underline:
        return None
    if len(set(underline)) == 1 and underline[0] in RST_HEADING_UNDERLINE and len(underline) >= len(title):
        return title
    return None


def extract_file_snippets(root: Path, path: Path, max_per_file: int) -> list[DocumentationSnippet]:
    relpath = posix_relpath(path, root)
    lines = read_text(path).splitlines()
    snippets: list[DocumentationSnippet] = []
    seen_text: set[str] = set()

    for index, line in enumerate(lines):
        heading: str | None = None
        match = HEADING_RE.match(line)
        if match:
            heading = _clean_line(match.group("title"))
            paragraph = _paragraph_after(lines, index + 1)
        else:
            heading = _rst_heading(lines, index)
            paragraph = _paragraph_after(lines, index + 2) if heading else None
        if not heading or not paragraph:
            continue
        paragraph_line, text = paragraph
        if text in seen_text:
            continue
        seen_text.add(text)
        snippets.append(
            DocumentationSnippet(
                file=relpath,
                line=paragraph_line,
                heading=heading,
                text=text,
            )
        )
        if len(snippets) >= max_per_file:
            break

    if not snippets:
        paragraph = _paragraph_after(lines, 0)
        if paragraph:
            paragraph_line, text = paragraph
            snippets.append(
                DocumentationSnippet(
                    file=relpath,
                    line=paragraph_line,
                    heading=None,
                    text=text,
                )
            )

    return snippets


def extract_documentation(root: str | Path, *, max_per_file: int = 6) -> DocumentationIndex:
    root_path = Path(root).resolve()
    snippets: list[DocumentationSnippet] = []
    for path in iter_repo_files(root_path):
        rel_parts = path.relative_to(root_path).parts
        if not is_documentation(path):
            continue
        if len(rel_parts) > 1 and rel_parts[0] not in {"doc", "docs", "Documentation"}:
            continue
        snippets.extend(extract_file_snippets(root_path, path, max_per_file))

    snippets.sort(key=lambda item: (item.file, item.line, item.heading or "", item.text))
    return DocumentationIndex(snippets=snippets)
