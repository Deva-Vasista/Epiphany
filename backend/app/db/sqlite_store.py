import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from typing import Any, Generator, Optional
from uuid import uuid4

from app.config import get_settings


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT 'Untitled session',
  chat_json TEXT NOT NULL DEFAULT '[]',
  canvas_json TEXT NOT NULL DEFAULT '{"charts":[],"layout":[]}',
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  duckdb_table_name TEXT NOT NULL,
  schema_json TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS dashboards (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  title TEXT NOT NULL,
  question_text TEXT NOT NULL,
  chart_type TEXT,
  vega_lite_spec_json TEXT NOT NULL,
  starred BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS boards (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL DEFAULT '',
  user_id TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  question_text TEXT NOT NULL,
  chat_json TEXT NOT NULL,
  charts_json TEXT NOT NULL,
  layout_json TEXT NOT NULL,
  starred BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id);
CREATE INDEX IF NOT EXISTS idx_dashboards_session ON dashboards(session_id);
CREATE INDEX IF NOT EXISTS idx_boards_session ON boards(session_id);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(str(settings.sqlite_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        # Migrate older DBs that predate user-scoped sessions
        _ensure_column(conn, "sessions", "user_id", "user_id TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "sessions", "title", "title TEXT NOT NULL DEFAULT 'Untitled session'")
        _ensure_column(conn, "sessions", "chat_json", "chat_json TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(
            conn,
            "sessions",
            "canvas_json",
            "canvas_json TEXT NOT NULL DEFAULT '{\"charts\":[],\"layout\":[]}'",
        )
        _ensure_column(conn, "sessions", "updated_at", "updated_at TIMESTAMP")
        conn.execute(
            "UPDATE sessions SET updated_at = created_at WHERE updated_at IS NULL OR updated_at = ''"
        )
        # Index after user_id is guaranteed to exist on migrated DBs
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
        )
        # Boards are user-scoped (survive session switches / deletes)
        _ensure_column(conn, "boards", "user_id", "user_id TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            UPDATE boards
            SET user_id = COALESCE(
              (SELECT user_id FROM sessions WHERE sessions.id = boards.session_id),
              ''
            )
            WHERE user_id IS NULL OR user_id = ''
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_boards_user ON boards(user_id)"
        )
        conn.commit()


@contextmanager
def db_cursor() -> Generator[sqlite3.Cursor, None, None]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_user(user_id: str) -> str:
    uid = (user_id or "").strip() or str(uuid4())
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE id = ?", (uid,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (id, created_at) VALUES (?, ?)",
                (uid, _utcnow()),
            )
    return uid


def create_session(user_id: str, title: Optional[str] = None) -> dict[str, Any]:
    uid = ensure_user(user_id)
    session_id = str(uuid4())
    now = _utcnow()
    label = (title or "").strip() or f"Session {now[:16].replace('T', ' ')}"
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO sessions
              (id, user_id, title, chat_json, canvas_json, created_at, updated_at)
            VALUES (?, ?, ?, '[]', '{"charts":[],"layout":[]}', ?, ?)
            """,
            (session_id, uid, label, now, now),
        )
    return get_session(session_id)  # type: ignore[return-value]


def list_sessions(user_id: str) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, title, created_at, updated_at
            FROM sessions
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_session(session_id: str) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, title, chat_json, canvas_json, created_at, updated_at
            FROM sessions WHERE id = ?
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["chat"] = json.loads(d.pop("chat_json") or "[]")
        except Exception:
            d["chat"] = []
            d.pop("chat_json", None)
        try:
            canvas = json.loads(d.pop("canvas_json") or "{}")
        except Exception:
            canvas = {}
            d.pop("canvas_json", None)
        d["charts"] = canvas.get("charts") or []
        d["layout"] = canvas.get("layout") or []
        return d


def touch_session(session_id: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_utcnow(), session_id),
        )


def update_session_title(session_id: str, title: str) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title.strip() or "Untitled session", _utcnow(), session_id),
        )
        if cur.rowcount == 0:
            return None
    return get_session(session_id)


def save_session_chat(session_id: str, chat: list[Any]) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE sessions SET chat_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(chat), _utcnow(), session_id),
        )
        if cur.rowcount == 0:
            return None
    return get_session(session_id)


def save_session_canvas(
    session_id: str,
    charts: list[Any],
    layout: list[Any],
) -> Optional[dict[str, Any]]:
    payload = json.dumps({"charts": charts, "layout": layout})
    with db_cursor() as cur:
        cur.execute(
            "UPDATE sessions SET canvas_json = ?, updated_at = ? WHERE id = ?",
            (payload, _utcnow(), session_id),
        )
        if cur.rowcount == 0:
            return None
    return get_session(session_id)


def session_exists(session_id: str) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
        return cur.fetchone() is not None


def delete_session(session_id: str) -> bool:
    """Delete session-local data. Boards stay (keyed by user_id)."""
    conn = get_connection()
    try:
        # Boards may still reference this session_id; don't block delete.
        conn.execute("PRAGMA foreign_keys = OFF")
        cur = conn.cursor()
        cur.execute("DELETE FROM dashboards WHERE session_id = ?", (session_id,))
        cur.execute("DELETE FROM files WHERE session_id = ?", (session_id,))
        cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_file(
    session_id: str,
    filename: str,
    duckdb_table_name: str,
    schema_json: str,
) -> dict[str, Any]:
    file_id = str(uuid4())
    created_at = _utcnow()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (id, session_id, filename, duckdb_table_name, schema_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, session_id, filename, duckdb_table_name, schema_json, created_at),
        )
    return {
        "id": file_id,
        "session_id": session_id,
        "filename": filename,
        "duckdb_table_name": duckdb_table_name,
        "schema_json": schema_json,
        "created_at": created_at,
    }


def list_files(session_id: str) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, filename, duckdb_table_name, schema_json, created_at
            FROM files WHERE session_id = ? ORDER BY created_at
            """,
            (session_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_session_table_names(session_id: str) -> list[str]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT duckdb_table_name FROM files WHERE session_id = ?",
            (session_id,),
        )
        return [row["duckdb_table_name"] for row in cur.fetchall()]


def insert_dashboard(
    session_id: str,
    title: str,
    question_text: str,
    chart_type: Optional[str],
    vega_lite_spec_json: str,
    *,
    idempotent_seconds: int = 5,
) -> dict[str, Any]:
    """Insert a dashboard snapshot. Skips duplicates of same title+chart_type within a short window."""
    # Idempotency: same session + title + chart_type within N seconds → return existing
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, title, question_text, chart_type,
                   vega_lite_spec_json, starred, created_at
            FROM dashboards
            WHERE session_id = ?
              AND title = ?
              AND IFNULL(chart_type, '') = IFNULL(?, '')
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (session_id, title, chart_type),
        )
        now = datetime.now(timezone.utc)
        for row in cur.fetchall():
            try:
                created = datetime.fromisoformat(str(row["created_at"]))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if (now - created).total_seconds() <= idempotent_seconds:
                    d = dict(row)
                    d["starred"] = bool(d["starred"])
                    d["deduped"] = True
                    return d
            except Exception:
                continue

    dash_id = str(uuid4())
    created_at = _utcnow()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO dashboards
              (id, session_id, title, question_text, chart_type, vega_lite_spec_json, starred, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                dash_id,
                session_id,
                title,
                question_text,
                chart_type,
                vega_lite_spec_json,
                created_at,
            ),
        )
    return {
        "id": dash_id,
        "session_id": session_id,
        "title": title,
        "question_text": question_text,
        "chart_type": chart_type,
        "vega_lite_spec_json": vega_lite_spec_json,
        "starred": False,
        "created_at": created_at,
        "deduped": False,
    }


def delete_dashboard(dashboard_id: str) -> bool:
    with db_cursor() as cur:
        cur.execute("DELETE FROM dashboards WHERE id = ?", (dashboard_id,))
        return cur.rowcount > 0


def list_dashboards(session_id: str) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, title, question_text, chart_type,
                   vega_lite_spec_json, starred, created_at
            FROM dashboards
            WHERE session_id = ?
            ORDER BY starred DESC, created_at DESC
            """,
            (session_id,),
        )
        rows = []
        for row in cur.fetchall():
            d = dict(row)
            d["starred"] = bool(d["starred"])
            rows.append(d)
        return rows


def get_dashboard(dashboard_id: str) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, title, question_text, chart_type,
                   vega_lite_spec_json, starred, created_at
            FROM dashboards WHERE id = ?
            """,
            (dashboard_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["starred"] = bool(d["starred"])
        return d


def toggle_star(dashboard_id: str) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute("SELECT starred FROM dashboards WHERE id = ?", (dashboard_id,))
        row = cur.fetchone()
        if not row:
            return None
        new_val = 0 if row["starred"] else 1
        cur.execute(
            "UPDATE dashboards SET starred = ? WHERE id = ?",
            (new_val, dashboard_id),
        )
    return get_dashboard(dashboard_id)


def insert_board(
    session_id: str,
    title: str,
    question_text: str,
    chat_json: str,
    charts_json: str,
    layout_json: str,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Save a board keyed by user_id (global) with originating session_id."""
    board_id = str(uuid4())
    created_at = _utcnow()
    uid = (user_id or "").strip()
    if not uid:
        session = get_session(session_id)
        uid = (session or {}).get("user_id") or ""
    if not uid:
        raise ValueError("user_id is required to save a board")
    ensure_user(uid)
    with db_cursor() as cur:
        # Soft-reference session_id (may outlive the session row)
        cur.execute(
            """
            INSERT INTO boards
              (id, session_id, user_id, title, question_text, chat_json, charts_json,
               layout_json, starred, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                board_id,
                session_id or "",
                uid,
                title,
                question_text,
                chat_json,
                charts_json,
                layout_json,
                created_at,
            ),
        )
    return {
        "id": board_id,
        "session_id": session_id or "",
        "user_id": uid,
        "title": title,
        "question_text": question_text,
        "chat_json": chat_json,
        "charts_json": charts_json,
        "layout_json": layout_json,
        "starred": False,
        "created_at": created_at,
    }


def update_board(
    board_id: str,
    *,
    title: Optional[str] = None,
    question_text: Optional[str] = None,
    chat_json: Optional[str] = None,
    charts_json: Optional[str] = None,
    layout_json: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Replace contents of an existing board (no duplicate insert)."""
    existing = get_board(board_id)
    if not existing:
        return None
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE boards
            SET title = ?,
                question_text = ?,
                chat_json = ?,
                charts_json = ?,
                layout_json = ?
            WHERE id = ?
            """,
            (
                (title if title is not None else existing["title"]),
                (
                    question_text
                    if question_text is not None
                    else existing["question_text"]
                ),
                chat_json if chat_json is not None else existing["chat_json"],
                charts_json if charts_json is not None else existing["charts_json"],
                layout_json if layout_json is not None else existing["layout_json"],
                board_id,
            ),
        )
        if cur.rowcount == 0:
            return None
    return get_board(board_id)


def list_boards(user_id: str) -> list[dict[str, Any]]:
    """List all boards for a user across sessions."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, user_id, title, question_text, charts_json, starred, created_at
            FROM boards
            WHERE user_id = ?
            ORDER BY starred DESC, created_at DESC
            """,
            (user_id,),
        )
        rows = []
        for row in cur.fetchall():
            d = dict(row)
            d["starred"] = bool(d["starred"])
            try:
                charts = json.loads(d.pop("charts_json") or "[]")
            except Exception:
                charts = []
            d["chart_count"] = len(charts) if isinstance(charts, list) else 0
            rows.append(d)
        return rows


def get_board(board_id: str) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, user_id, title, question_text, chat_json, charts_json,
                   layout_json, starred, created_at
            FROM boards WHERE id = ?
            """,
            (board_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["starred"] = bool(d["starred"])
        return d


def update_board_layout(board_id: str, layout_json: str) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE boards SET layout_json = ? WHERE id = ?",
            (layout_json, board_id),
        )
        if cur.rowcount == 0:
            return None
    return get_board(board_id)


def toggle_board_star(board_id: str) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute("SELECT starred FROM boards WHERE id = ?", (board_id,))
        row = cur.fetchone()
        if not row:
            return None
        new_val = 0 if row["starred"] else 1
        cur.execute("UPDATE boards SET starred = ? WHERE id = ?", (new_val, board_id))
    return get_board(board_id)


def delete_board(board_id: str) -> bool:
    with db_cursor() as cur:
        cur.execute("DELETE FROM boards WHERE id = ?", (board_id,))
        return cur.rowcount > 0
