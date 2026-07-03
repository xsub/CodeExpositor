"""SQLite storage for canonical graph nodes, edges, evidence and adjacency."""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from expositor.model import Edge, Evidence, Graph, Node


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    path TEXT,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    type TEXT NOT NULL,
    confidence TEXT NOT NULL,
    extraction_tool TEXT NOT NULL,
    build_context TEXT,
    architecture_context TEXT,
    index_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY(source) REFERENCES nodes(id),
    FOREIGN KEY(target) REFERENCES nodes(id)
);

CREATE TABLE IF NOT EXISTS evidence (
    edge_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    path TEXT NOT NULL,
    line INTEGER,
    column INTEGER,
    snippet TEXT,
    PRIMARY KEY(edge_id, position),
    FOREIGN KEY(edge_id) REFERENCES edges(id)
);

CREATE TABLE IF NOT EXISTS adjacency (
    node_id TEXT NOT NULL,
    neighbor_id TEXT NOT NULL,
    edge_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('out', 'in')),
    PRIMARY KEY(node_id, neighbor_id, edge_id, direction),
    FOREIGN KEY(node_id) REFERENCES nodes(id),
    FOREIGN KEY(neighbor_id) REFERENCES nodes(id),
    FOREIGN KEY(edge_id) REFERENCES edges(id)
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
CREATE INDEX IF NOT EXISTS idx_adjacency_node ON adjacency(node_id, direction);
CREATE INDEX IF NOT EXISTS idx_adjacency_edge_type ON adjacency(edge_type);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def save_graph(path: str | Path, graph: Graph) -> None:
    with closing(connect(path)) as connection:
        initialize(connection)
        with connection:
            connection.execute("DELETE FROM adjacency")
            connection.execute("DELETE FROM evidence")
            connection.execute("DELETE FROM edges")
            connection.execute("DELETE FROM nodes")

            for node in sorted(graph.nodes.values(), key=lambda item: item.id):
                connection.execute(
                    """
                    INSERT INTO nodes (id, type, label, path, metadata_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        node.id,
                        node.type,
                        node.label,
                        node.path,
                        json.dumps(node.metadata, sort_keys=True),
                    ),
                )

            for edge in sorted(graph.edges.values(), key=lambda item: item.id):
                connection.execute(
                    """
                    INSERT INTO edges (
                        id, source, target, type, confidence, extraction_tool,
                        build_context, architecture_context, index_version, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge.id,
                        edge.source,
                        edge.target,
                        edge.type,
                        edge.confidence,
                        edge.extraction_tool,
                        edge.build_context,
                        edge.architecture_context,
                        edge.index_version,
                        json.dumps(edge.metadata, sort_keys=True),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO adjacency (node_id, neighbor_id, edge_id, edge_type, direction)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (edge.source, edge.target, edge.id, edge.type, "out"),
                )
                connection.execute(
                    """
                    INSERT INTO adjacency (node_id, neighbor_id, edge_id, edge_type, direction)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (edge.target, edge.source, edge.id, edge.type, "in"),
                )
                for position, evidence in enumerate(edge.evidence):
                    connection.execute(
                        """
                        INSERT INTO evidence (edge_id, position, path, line, column, snippet)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            edge.id,
                            position,
                            evidence.path,
                            evidence.line,
                            evidence.column,
                            evidence.snippet,
                        ),
                    )


def adjacency_counts(path: str | Path) -> dict[str, int]:
    with closing(connect(path)) as connection:
        initialize(connection)
        rows = connection.execute(
            "SELECT direction, COUNT(*) AS count FROM adjacency GROUP BY direction"
        ).fetchall()
        return {row["direction"]: int(row["count"]) for row in rows}


def _count_rows(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def _group_counts(connection: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    rows = connection.execute(
        f"SELECT {column} AS value, COUNT(*) AS count FROM {table} GROUP BY {column}"
    ).fetchall()
    return {str(row["value"]): int(row["count"]) for row in rows}


def storage_info(path: str | Path) -> dict[str, object]:
    """Inspect a SQLite graph store without rebuilding the graph."""

    db_path = Path(path)
    if not db_path.exists():
        return {
            "path": db_path.as_posix(),
            "exists": False,
            "initialized": False,
            "ok": False,
            "counts": {},
            "adjacency_counts": {},
            "node_type_counts": {},
            "edge_type_counts": {},
            "issues": ["database file does not exist"],
        }

    required_tables = {"nodes", "edges", "evidence", "adjacency"}
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        tables = {str(row["name"]) for row in rows}
        missing_tables = sorted(required_tables - tables)
        if missing_tables:
            return {
                "path": db_path.as_posix(),
                "exists": True,
                "initialized": False,
                "ok": False,
                "counts": {},
                "adjacency_counts": {},
                "node_type_counts": {},
                "edge_type_counts": {},
                "issues": [f"missing table: {table}" for table in missing_tables],
            }

        counts = {table: _count_rows(connection, table) for table in sorted(required_tables)}
        adjacency = _group_counts(connection, "adjacency", "direction")
        issues = []
        edge_count = counts["edges"]
        if adjacency.get("out", 0) != edge_count:
            issues.append("out adjacency row count does not match edge count")
        if adjacency.get("in", 0) != edge_count:
            issues.append("in adjacency row count does not match edge count")

        return {
            "path": db_path.as_posix(),
            "exists": True,
            "initialized": True,
            "ok": not issues,
            "counts": counts,
            "adjacency_counts": dict(sorted(adjacency.items())),
            "node_type_counts": dict(sorted(_group_counts(connection, "nodes", "type").items())),
            "edge_type_counts": dict(sorted(_group_counts(connection, "edges", "type").items())),
            "issues": issues,
        }


def load_graph(path: str | Path) -> Graph:
    with closing(connect(path)) as connection:
        initialize(connection)
        graph = Graph()
        for row in connection.execute("SELECT * FROM nodes ORDER BY id"):
            graph.nodes[row["id"]] = Node(
                id=row["id"],
                type=row["type"],
                label=row["label"],
                path=row["path"],
                metadata=json.loads(row["metadata_json"]),
            )

        evidence_by_edge: dict[str, list[Evidence]] = {}
        for row in connection.execute("SELECT * FROM evidence ORDER BY edge_id, position"):
            evidence_by_edge.setdefault(row["edge_id"], []).append(
                Evidence(
                    path=row["path"],
                    line=row["line"],
                    column=row["column"],
                    snippet=row["snippet"],
                )
            )

        for row in connection.execute("SELECT * FROM edges ORDER BY id"):
            graph.edges[row["id"]] = Edge(
                id=row["id"],
                source=row["source"],
                target=row["target"],
                type=row["type"],
                confidence=row["confidence"],
                extraction_tool=row["extraction_tool"],
                evidence=evidence_by_edge.get(row["id"], []),
                build_context=row["build_context"],
                architecture_context=row["architecture_context"],
                index_version=row["index_version"],
                metadata=json.loads(row["metadata_json"]),
            )
        return graph
