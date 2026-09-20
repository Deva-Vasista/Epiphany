"""File upload and schema profiling."""

from __future__ import annotations

import io
import json
from typing import Any

import pandas as pd
from fastapi import UploadFile

from app.db import duckdb_store, sqlite_store


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


async def load_frames_from_upload(upload: UploadFile) -> list[tuple[str, pd.DataFrame]]:
    filename = upload.filename or "upload.csv"
    lower = filename.lower()
    content = await upload.read()
    if not content:
        raise ValueError(f"File '{filename}' is empty")

    if lower.endswith(".csv"):
        try:
            df = pd.read_csv(io.BytesIO(content))
        except Exception as exc:
            raise ValueError(f"Could not parse CSV '{filename}': {exc}") from exc
        if df.empty:
            raise ValueError(f"CSV '{filename}' has no rows")
        return [(filename, df)]

    if lower.endswith((".xlsx", ".xls")):
        try:
            sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
        except Exception as exc:
            raise ValueError(f"Could not parse Excel '{filename}': {exc}") from exc
        frames: list[tuple[str, pd.DataFrame]] = []
        for sheet_name, df in sheets.items():
            if df is None or df.empty:
                continue
            label = f"{filename}::{sheet_name}"
            frames.append((label, df))
        if not frames:
            raise ValueError(f"Excel '{filename}' has no non-empty sheets")
        return frames

    raise ValueError(f"Unsupported file type for '{filename}'. Use CSV or Excel.")


async def process_uploads(session_id: str, uploads: list[UploadFile]) -> list[dict[str, Any]]:
    existing = set(sqlite_store.get_session_table_names(session_id))
    results: list[dict[str, Any]] = []

    for upload in uploads:
        frames = await load_frames_from_upload(upload)
        for label, df in frames:
            table_name = duckdb_store.sanitize_table_name(label, existing)
            existing.add(table_name)
            profile = duckdb_store.register_dataframe(session_id, df, table_name)
            record = sqlite_store.insert_file(
                session_id=session_id,
                filename=label,
                duckdb_table_name=table_name,
                schema_json=json.dumps(profile),
            )
            results.append(
                {
                    "id": record["id"],
                    "filename": record["filename"],
                    "duckdb_table_name": record["duckdb_table_name"],
                    "schema": profile,
                    "created_at": record["created_at"],
                }
            )
    return results


def schema_catalog_for_session(session_id: str) -> str:
    """Compact schema catalog for the LLM (no sample-row dumps)."""
    files = sqlite_store.list_files(session_id)
    if not files:
        return "No files uploaded yet."
    parts: list[str] = []
    for f in files:
        schema = json.loads(f["schema_json"])
        cols = ", ".join(f"{c['name']}:{c['dtype']}" for c in schema["columns"])
        parts.append(
            f"`{schema['table_name']}` ({schema['row_count']} rows) — {cols}"
        )
    return "\n".join(parts)
