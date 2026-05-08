# Input: SQLite database path and JSON source (file path or dict in output_json_format).
# Output: Initialized SQLite database with loaded document/node data; query helpers for doc_pk lookup.
# Position: Database initialization, JSON-to-DB loader, and document queries. If modified, update this header and the parent folder's .md index.

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

_SCHEMA_SQL = """\
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  doc_pk            INTEGER PRIMARY KEY,
  doc_name          TEXT NOT NULL UNIQUE,
  doc_description   TEXT,
  company           TEXT,
  year_period       TEXT,
  raw_json          TEXT NOT NULL CHECK (json_valid(raw_json)),
  checksum          TEXT,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS nodes (
  node_pk           INTEGER PRIMARY KEY,
  doc_pk            INTEGER NOT NULL
                    REFERENCES documents(doc_pk) ON DELETE CASCADE,
  node_id           TEXT NOT NULL,
  parent_node_pk    INTEGER
                    REFERENCES nodes(node_pk) ON DELETE CASCADE,
  child_order       INTEGER NOT NULL DEFAULT 0,
  depth             INTEGER NOT NULL DEFAULT 0,
  title             TEXT NOT NULL,
  start_index       INTEGER NOT NULL,
  end_index         INTEGER NOT NULL,
  summary           TEXT,
  prefix_summary    TEXT,
  text_content      TEXT,
  CHECK (length(node_id) > 0),
  CHECK (end_index >= start_index),
  UNIQUE (doc_pk, node_id)
);

CREATE TABLE IF NOT EXISTS node_chunks (
  chunk_pk          INTEGER PRIMARY KEY,
  doc_pk            INTEGER NOT NULL
                    REFERENCES documents(doc_pk) ON DELETE CASCADE,
  node_pk           INTEGER NOT NULL
                    REFERENCES nodes(node_pk) ON DELETE CASCADE,
  chunk_text        TEXT NOT NULL,
  page_start        INTEGER,
  page_end          INTEGER,
  token_count       INTEGER,
  vector_ref        TEXT UNIQUE,
  metadata_json     TEXT CHECK (metadata_json IS NULL OR json_valid(metadata_json)),
  CHECK (page_start IS NULL OR page_end IS NULL OR page_end >= page_start)
);

CREATE INDEX IF NOT EXISTS idx_nodes_doc_parent_order
  ON nodes(doc_pk, parent_node_pk, child_order);

CREATE INDEX IF NOT EXISTS idx_nodes_doc_node_id
  ON nodes(doc_pk, node_id);

CREATE INDEX IF NOT EXISTS idx_nodes_doc_start_end
  ON nodes(doc_pk, start_index, end_index);

CREATE INDEX IF NOT EXISTS idx_chunks_node
  ON node_chunks(node_pk);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_pages
  ON node_chunks(doc_pk, page_start, page_end);

CREATE TABLE IF NOT EXISTS workflows (
  workflow_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  company_name      TEXT NOT NULL,
  data_source       TEXT NOT NULL,
  year_periods      TEXT NOT NULL CHECK (json_valid(year_periods)),
  sct_data          TEXT NOT NULL CHECK (json_valid(sct_data)),
  metric_count      INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_workflows_company
  ON workflows(company_name, created_at DESC);
"""


def init_db(db_path: str = "static/tree_poc.db") -> sqlite3.Connection:
    """Create database tables and indexes if they do not exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_SQL)

    # Migration: add columns that may not exist in older databases
    for col, col_def in [
        ("company", "TEXT"),
        ("year_period", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {col_def}")
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.commit()
    return conn


def _compute_checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assign_node_ids(nodes: List[Dict[str, Any]], prefix: str = "") -> None:
    """Generate node_id for records that lack one (zero-padded 4-digit)."""
    for idx, node_data in enumerate(nodes):
        if "node_id" not in node_data or not node_data["node_id"]:
            node_data["node_id"] = f"{prefix}{idx:04d}"
        children = node_data.get("nodes", [])
        if children:
            _assign_node_ids(children, prefix=node_data["node_id"])


def _insert_nodes_recursive(
    cursor: sqlite3.Cursor,
    doc_pk: int,
    nodes: List[Dict[str, Any]],
    parent_node_pk: Optional[int],
    depth: int,
) -> int:
    """Recursively insert hierarchical nodes. Returns total inserted count."""
    inserted = 0
    for child_order, node_data in enumerate(nodes):
        cursor.execute(
            """INSERT INTO nodes
               (doc_pk, node_id, parent_node_pk, child_order, depth,
                title, start_index, end_index, summary, text_content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_pk,
                node_data["node_id"],
                parent_node_pk,
                child_order,
                depth,
                node_data["title"],
                node_data["start_index"],
                node_data["end_index"],
                node_data.get("summary"),
                node_data.get("text"),
            ),
        )
        current_node_pk = cursor.lastrowid
        inserted += 1

        children = node_data.get("nodes", [])
        if children:
            inserted += _insert_nodes_recursive(
                cursor, doc_pk, children, current_node_pk, depth + 1
            )

    return inserted


def load_json_to_db(
    source: Union[str, Path, Dict[str, Any]],
    db_path: str = "static/tree_poc.db",
    verbose: bool = True,
    *,
    company: str | None = None,
    year_period: str | None = None,
) -> Dict[str, Any]:
    """
    Load a JSON source (file path or dict) into the database.

    Handles two formats:
    - output_json_format: top-level "structure" key with recursive nodes.
    - Pipeline output: top-level "records" key with flat node list (each item
      has title, start_index, end_index, summary, text, nodes).

    Always stores the full JSON as raw_json in the documents table,
    then inserts each record as a row in the nodes table.

    Returns summary dict with doc_pk, doc_name, and node_count.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            raise ValueError(f"JSON file not found: {source}")
        raw_text = path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    elif isinstance(source, dict):
        raw_text = json.dumps(source, ensure_ascii=False)
        data = source
    else:
        raise TypeError("source must be a file path (str/Path) or a dict")

    doc_name = data.get("doc_name") or data.get("pdf_name")
    if not doc_name:
        raise ValueError('JSON must include "doc_name" or "pdf_name"')

    doc_description = data.get("doc_description")
    checksum = _compute_checksum(raw_text)

    conn = init_db(db_path)
    cursor = conn.cursor()

    try:
        # To handle re-loading the same document name, we delete the existing one first.
        # Since nodes and node_chunks have ON DELETE CASCADE, this cleans up associated data.
        #TEST
        cursor.execute("DELETE FROM documents WHERE doc_name = ?", (doc_name,))

        cursor.execute(
            """INSERT INTO documents (doc_name, doc_description, company, year_period, raw_json, checksum)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (doc_name, doc_description, company, year_period, raw_text, checksum),
        )
        doc_pk = cursor.lastrowid

        node_count = 0

        # Prefer hierarchical "structure"; fall back to flat "records"
        nodes_to_insert = data.get("structure")
        if not nodes_to_insert:
            nodes_to_insert = data.get("records")

        if nodes_to_insert and isinstance(nodes_to_insert, list):
            _assign_node_ids(nodes_to_insert)
            node_count = _insert_nodes_recursive(
                cursor, doc_pk, nodes_to_insert, parent_node_pk=None, depth=0
            )

        conn.commit()

        if verbose:
            print(f"[DB] Loaded '{doc_name}' -> doc_pk={doc_pk}, nodes={node_count}")

        return {"doc_pk": doc_pk, "doc_name": doc_name, "node_count": node_count}

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_documents(db_path: str = "static/tree_poc.db") -> List[Dict[str, Any]]:
    """Return all documents with their node counts."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """SELECT d.doc_pk, d.doc_name, d.doc_description, d.created_at,
                  COUNT(n.node_pk) AS node_count
           FROM documents d
           LEFT JOIN nodes n ON n.doc_pk = d.doc_pk
           GROUP BY d.doc_pk
           ORDER BY d.created_at DESC"""
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def list_companies(db_path: str = "static/tree_poc.db") -> list[str]:
    """Return distinct company names that have document trees in the DB."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT company FROM documents WHERE company IS NOT NULL AND company != '' ORDER BY company"
    )
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_document(
    identifier: Union[int, str],
    db_path: str = "static/tree_poc.db",
) -> Dict[str, Any]:
    """Look up a document by doc_pk (int) or doc_name (str)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if isinstance(identifier, int):
        cursor.execute("SELECT * FROM documents WHERE doc_pk = ?", (identifier,))
    else:
        cursor.execute("SELECT * FROM documents WHERE doc_name = ?", (identifier,))

    row = cursor.fetchone()
    conn.close()

    if row is None:
        raise ValueError(f"Document not found: {identifier}")
    return dict(row)


def get_doc_by_company_year(
    company: str,
    year_period: str,
    db_path: str = "static/tree_poc.db",
) -> Dict[str, Any]:
    """Look up a document by company and year_period. Returns the newest match."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """SELECT * FROM documents
           WHERE company = ? AND year_period = ?
           ORDER BY created_at DESC LIMIT 1""",
        (company, year_period),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        raise ValueError(
            f"Document not found for company={company!r}, year_period={year_period!r}"
        )
    return dict(row)


# ---------------------------------------------------------------------------
# Workflow history CRUD
# ---------------------------------------------------------------------------

def save_workflow(
    company_name: str,
    data_source: str,
    year_periods: list[str],
    sct_data: dict[str, Any],
    db_path: str = "static/tree_poc.db",
) -> int:
    """Persist a completed spread workflow and return its workflow_id."""
    conn = init_db(db_path)
    cursor = conn.cursor()
    metric_count = sum(
        len(metrics) for metrics in sct_data.values() if isinstance(metrics, list)
    )
    cursor.execute(
        """INSERT INTO workflows (company_name, data_source, year_periods, sct_data, metric_count)
           VALUES (?, ?, ?, ?, ?)""",
        (
            company_name,
            data_source,
            json.dumps(year_periods, ensure_ascii=False),
            json.dumps(sct_data, ensure_ascii=False),
            metric_count,
        ),
    )
    conn.commit()
    workflow_id = cursor.lastrowid
    conn.close()
    return workflow_id


def list_workflows(
    company_name: str | None = None,
    db_path: str = "static/tree_poc.db",
) -> list[dict[str, Any]]:
    """Return all workflows, optionally filtered by company, newest first."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if company_name:
        cursor.execute(
            """SELECT workflow_id, company_name, data_source, year_periods, metric_count, created_at
               FROM workflows WHERE company_name = ? ORDER BY created_at DESC""",
            (company_name,),
        )
    else:
        cursor.execute(
            """SELECT workflow_id, company_name, data_source, year_periods, metric_count, created_at
               FROM workflows ORDER BY created_at DESC""",
        )
    rows = cursor.fetchall()
    conn.close()
    results: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        record["year_periods"] = json.loads(record["year_periods"])
        results.append(record)
    return results


def get_workflow(
    workflow_id: int,
    db_path: str = "static/tree_poc.db",
) -> dict[str, Any]:
    """Return a single workflow with its full SCT data."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM workflows WHERE workflow_id = ?",
        (workflow_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"Workflow not found: {workflow_id}")
    record = dict(row)
    record["year_periods"] = json.loads(record["year_periods"])
    record["sct_data"] = json.loads(record["sct_data"])
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Database initialization and JSON loader")
    parser.add_argument("--init-db", action="store_true", help="Initialize the database")
    parser.add_argument("--load-json", type=str, help="Load a JSON file into the database")
    parser.add_argument("--db-path", default="tree_poc.db", help="Database file path")
    args = parser.parse_args()

    if not args.init_db and not args.load_json:
        parser.print_help()
        exit(1)

    if args.init_db:
        init_db(args.db_path)
        print(f"Database initialized: {args.db_path}")

    if args.load_json:
        result = load_json_to_db(args.load_json, db_path=args.db_path)
        print(f"Loaded: doc_pk={result['doc_pk']}, nodes={result['node_count']}")
