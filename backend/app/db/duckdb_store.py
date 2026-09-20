"""Per-session DuckDB management."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from app.config import get_settings

_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def session_db_path(session_id: str) -> Path:
    return get_settings().data_dir / "sessions" / session_id / "data.duckdb"


def connect(session_id: str) -> duckdb.DuckDBPyConnection:
    path = session_db_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def sanitize_table_name(filename: str, existing: set[str]) -> str:
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[^a-z0-9_]+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_")
    if not stem or stem[0].isdigit():
        stem = f"t_{stem}" if stem else "table"
    stem = stem[:50]
    if not _TABLE_RE.match(stem):
        stem = "table"
    name = stem
    i = 2
    while name in existing:
        name = f"{stem}_{i}"
        i += 1
    return name


def profile_dataframe(df: pd.DataFrame, table_name: str) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    n = len(df)
    for col in df.columns:
        series = df[col]
        null_count = int(series.isna().sum())
        null_pct = round(100.0 * null_count / n, 2) if n else 0.0
        dtype = str(series.dtype)
        sample = series.dropna().head(5).astype(str).tolist()
        try:
            cardinality = int(series.nunique(dropna=True))
        except TypeError:
            cardinality = None
        columns.append(
            {
                "name": str(col),
                "dtype": dtype,
                "null_count": null_count,
                "null_pct": null_pct,
                "cardinality": cardinality,
                "sample_values": sample,
            }
        )
    sample_rows = json.loads(df.head(5).to_json(orient="records", date_format="iso"))
    return {
        "table_name": table_name,
        "row_count": n,
        "column_count": len(df.columns),
        "columns": columns,
        "sample_rows": sample_rows,
    }


def register_dataframe(
    session_id: str,
    df: pd.DataFrame,
    table_name: str,
) -> dict[str, Any]:
    # Normalize column names to strings
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    with connect(session_id) as con:
        con.register("_upload_df", df)
        con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM _upload_df')
        con.unregister("_upload_df")
    return profile_dataframe(df, table_name)


def list_registered_tables(session_id: str) -> list[str]:
    path = session_db_path(session_id)
    if not path.exists():
        return []
    with connect(session_id) as con:
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    return [r[0] for r in rows]


def execute_select(
    session_id: str,
    sql: str,
    row_limit: int,
) -> list[dict[str, Any]]:
    with connect(session_id) as con:
        # Clamp result size
        limited = f"SELECT * FROM ({sql}) AS _q LIMIT {int(row_limit)}"
        rel = con.execute(limited)
        cols = [d[0] for d in rel.description]
        rows = rel.fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for k, v in zip(cols, row):
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif isinstance(v, (bytes, bytearray)):
                item[k] = v.decode("utf-8", errors="replace")
            else:
                item[k] = v
        result.append(item)
    return result
