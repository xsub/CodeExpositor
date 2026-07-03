"""Optional Graphviz renderer adapter."""

from __future__ import annotations

import shutil
import subprocess

from expositor.exporters.dot import graph_to_dot
from expositor.model import Graph


def graphviz_available(executable: str = "dot") -> bool:
    return shutil.which(executable) is not None


def dot_to_graphviz_svg(dot: str, *, executable: str = "dot") -> str:
    path = shutil.which(executable)
    if not path:
        raise RuntimeError(f"{executable} executable not found")
    completed = subprocess.run(
        [path, "-Tsvg"],
        input=dot,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or f"{executable} exited with status {completed.returncode}"
        raise RuntimeError(message)
    return completed.stdout


def graph_to_graphviz_svg(
    graph: Graph,
    graph_filter: str = "all",
    *,
    executable: str = "dot",
) -> str:
    return dot_to_graphviz_svg(
        graph_to_dot(graph, graph_filter),
        executable=executable,
    )
