"""SQL query tool with server-side validation."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from app.config import get_settings
from app.db import duckdb_store, sqlite_store


FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
    "ATTACH",
    "COPY",
    "PRAGMA",
    "EXPORT",
    "IMPORT",
    "INSTALL",
    "LOAD",
    "CALL",
    "EXECUTE",
    "REPLACE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
}


class QueryValidationError(ValueError):
    pass


def _collect_table_names(node: exp.Expression) -> set[str]:
    names: set[str] = set()
    for table in node.find_all(exp.Table):
        name = table.name
        if name:
            names.add(name.lower())
    return names


def validate_select_sql(sql: str, allowed_tables: set[str]) -> str:
    cleaned = sql.strip().rstrip(";")
    if not cleaned:
        raise QueryValidationError("Empty SQL")

    upper = cleaned.upper()
    for kw in FORBIDDEN_KEYWORDS:
        # crude keyword guard before parse
        if f" {kw} " in f" {upper} " or upper.startswith(f"{kw} "):
            raise QueryValidationError(f"Forbidden SQL keyword: {kw}")

    try:
        statements = sqlglot.parse(cleaned, read="duckdb")
    except Exception as exc:
        raise QueryValidationError(f"Could not parse SQL: {exc}") from exc

    if len(statements) != 1 or statements[0] is None:
        raise QueryValidationError("Only a single SQL statement is allowed")

    statement = statements[0]
    if not isinstance(statement, exp.Select) and not isinstance(statement, exp.Union):
        # WITH ... SELECT is often parsed as Select
        if not statement.find(exp.Select):
            raise QueryValidationError("Only SELECT queries are allowed")

    referenced = _collect_table_names(statement)
    allowed_lower = {t.lower() for t in allowed_tables}
    unknown = referenced - allowed_lower
    # Ignore CTE aliases: CTEs appear as tables too; allow names defined in WITH
    cte_names = {c.alias_or_name.lower() for c in statement.find_all(exp.CTE)}
    unknown = unknown - cte_names
    if unknown:
        raise QueryValidationError(
            f"Unknown or unauthorized table(s): {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(allowed_tables))}"
        )

    return cleaned


def query_data(session_id: str, sql: str, reasoning: str = "") -> dict[str, Any]:
    """Execute a validated read-only SELECT against the session DuckDB."""
    allowed = set(sqlite_store.get_session_table_names(session_id))
    if not allowed:
        return {"error": "no_tables", "message": "No uploaded tables in this session."}

    settings = get_settings()
    try:
        cleaned = validate_select_sql(sql, allowed)
        rows = duckdb_store.execute_select(
            session_id, cleaned, row_limit=settings.query_row_limit
        )
    except QueryValidationError as exc:
        return {"error": "invalid_sql", "message": str(exc), "reasoning": reasoning}
    except Exception as exc:
        return {"error": "query_failed", "message": str(exc), "reasoning": reasoning}

    return {
        "rows": rows,
        "row_count": len(rows),
        "truncated": len(rows) >= settings.query_row_limit,
        "reasoning": reasoning,
        "sql": cleaned,
    }
