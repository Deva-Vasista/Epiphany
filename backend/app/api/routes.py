import json
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.graph import run_agent_stream
from app.db import sqlite_store
from app.services import upload as upload_service

router = APIRouter()


class CreateSessionRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    title: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    save_dashboard: bool = False


class SessionChatRequest(BaseModel):
    chat: list[dict[str, Any]] = Field(default_factory=list)


class SessionCanvasRequest(BaseModel):
    charts: list[dict[str, Any]] = Field(default_factory=list)
    layout: list[dict[str, Any]] = Field(default_factory=list)


class RenameSessionRequest(BaseModel):
    title: str = Field(..., min_length=1)


def _ensure_session(session_id: str) -> None:
    if not sqlite_store.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/users/{user_id}")
def register_user(user_id: str) -> dict[str, str]:
    uid = sqlite_store.ensure_user(user_id)
    return {"user_id": uid}


@router.get("/users/{user_id}/sessions")
def list_user_sessions(user_id: str) -> dict[str, Any]:
    sqlite_store.ensure_user(user_id)
    return {"sessions": sqlite_store.list_sessions(user_id)}


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session(body: CreateSessionRequest) -> CreateSessionResponse:
    row = sqlite_store.create_session(body.user_id, body.title)
    return CreateSessionResponse(
        session_id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    row = sqlite_store.get_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: RenameSessionRequest) -> dict[str, Any]:
    row = sqlite_store.update_session_title(session_id, body.title)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


@router.put("/sessions/{session_id}/chat")
def save_chat(session_id: str, body: SessionChatRequest) -> dict[str, Any]:
    _ensure_session(session_id)
    row = sqlite_store.save_session_chat(session_id, body.chat)
    return {"ok": True, "updated_at": row["updated_at"] if row else None}


@router.put("/sessions/{session_id}/canvas")
def save_canvas(session_id: str, body: SessionCanvasRequest) -> dict[str, Any]:
    _ensure_session(session_id)
    row = sqlite_store.save_session_canvas(session_id, body.charts, body.layout)
    return {"ok": True, "updated_at": row["updated_at"] if row else None}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, Any]:
    if not sqlite_store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": session_id, "deleted": True}


@router.post("/sessions/{session_id}/upload")
async def upload_files(
    session_id: str,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    _ensure_session(session_id)
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    try:
        results = await upload_service.process_uploads(session_id, files)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"files": results, "count": len(results)}


@router.get("/sessions/{session_id}/files")
def list_files(session_id: str) -> dict[str, Any]:
    _ensure_session(session_id)
    files = sqlite_store.list_files(session_id)
    out = []
    for f in files:
        out.append(
            {
                "id": f["id"],
                "filename": f["filename"],
                "duckdb_table_name": f["duckdb_table_name"],
                "schema": json.loads(f["schema_json"]),
                "created_at": f["created_at"],
            }
        )
    return {"files": out}


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: str, body: ChatRequest) -> StreamingResponse:
    _ensure_session(session_id)
    files = sqlite_store.list_files(session_id)
    if not files:
        raise HTTPException(
            status_code=400,
            detail="Upload at least one CSV/Excel file before chatting",
        )
    sqlite_store.touch_session(session_id)

    async def event_generator():
        async for event in run_agent_stream(
            session_id=session_id,
            question=body.message,
            save_dashboard=body.save_dashboard,
        ):
            payload = json.dumps(event["data"], default=str)
            yield f"event: {event['event']}\ndata: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions/{session_id}/dashboards")
def list_dashboards(session_id: str) -> dict[str, Any]:
    _ensure_session(session_id)
    rows = sqlite_store.list_dashboards(session_id)
    dashboards = []
    for r in rows:
        dashboards.append(
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "title": r["title"],
                "question_text": r["question_text"],
                "chart_type": r["chart_type"],
                "vega_lite_spec": json.loads(r["vega_lite_spec_json"]),
                "starred": r["starred"],
                "created_at": r["created_at"],
            }
        )
    return {"dashboards": dashboards}


class PinDashboardRequest(BaseModel):
    title: str = Field(..., min_length=1)
    question_text: str = ""
    chart_type: Optional[str] = None
    vega_lite_spec: dict[str, Any]


@router.post("/sessions/{session_id}/dashboards")
def pin_dashboard(session_id: str, body: PinDashboardRequest) -> dict[str, Any]:
    _ensure_session(session_id)
    row = sqlite_store.insert_dashboard(
        session_id=session_id,
        title=body.title,
        question_text=body.question_text or body.title,
        chart_type=body.chart_type,
        vega_lite_spec_json=json.dumps(body.vega_lite_spec),
    )
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "title": row["title"],
        "question_text": row["question_text"],
        "chart_type": row["chart_type"],
        "vega_lite_spec": body.vega_lite_spec,
        "starred": row["starred"],
        "created_at": row["created_at"],
    }


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(dashboard_id: str) -> dict[str, Any]:
    row = sqlite_store.get_dashboard(dashboard_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "title": row["title"],
        "question_text": row["question_text"],
        "chart_type": row["chart_type"],
        "vega_lite_spec": json.loads(row["vega_lite_spec_json"]),
        "starred": row["starred"],
        "created_at": row["created_at"],
    }


@router.post("/dashboards/{dashboard_id}/star")
def star_dashboard(dashboard_id: str) -> dict[str, Any]:
    row = sqlite_store.toggle_star(dashboard_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return {
        "id": row["id"],
        "starred": row["starred"],
        "title": row["title"],
    }


@router.delete("/dashboards/{dashboard_id}")
def remove_dashboard(dashboard_id: str) -> dict[str, Any]:
    if not sqlite_store.delete_dashboard(dashboard_id):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return {"id": dashboard_id, "deleted": True}


class BoardChartIn(BaseModel):
    id: str
    title: str
    chart_type: Optional[str] = None
    vega_lite_spec: dict[str, Any]


class BoardSaveRequest(BaseModel):
    title: str = Field(..., min_length=1)
    question_text: str = ""
    chat: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[BoardChartIn] = Field(default_factory=list)
    layout: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/sessions/{session_id}/boards")
def save_board(session_id: str, body: BoardSaveRequest) -> dict[str, Any]:
    _ensure_session(session_id)
    if not body.charts:
        raise HTTPException(status_code=400, detail="Board must include at least one chart")
    session = sqlite_store.get_session(session_id) or {}
    user_id = (session.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="Session has no user_id")
    try:
        row = sqlite_store.insert_board(
            session_id=session_id,
            title=body.title,
            question_text=body.question_text or body.title,
            chat_json=json.dumps(body.chat),
            charts_json=json.dumps([c.model_dump() for c in body.charts]),
            layout_json=json.dumps(body.layout),
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "user_id": row.get("user_id"),
        "title": row["title"],
        "question_text": row["question_text"],
        "chart_count": len(body.charts),
        "starred": False,
        "created_at": row["created_at"],
    }


@router.get("/users/{user_id}/boards")
def list_user_boards(user_id: str) -> dict[str, Any]:
    sqlite_store.ensure_user(user_id)
    return {"boards": sqlite_store.list_boards(user_id)}


@router.get("/sessions/{session_id}/boards")
def list_session_boards(session_id: str) -> dict[str, Any]:
    """Backward-compatible: list boards for the session's user (global to that user)."""
    _ensure_session(session_id)
    session = sqlite_store.get_session(session_id) or {}
    user_id = session.get("user_id") or ""
    if not user_id:
        return {"boards": []}
    return {"boards": sqlite_store.list_boards(user_id)}


@router.put("/boards/{board_id}")
def update_board(board_id: str, body: BoardSaveRequest) -> dict[str, Any]:
    if not body.charts:
        raise HTTPException(status_code=400, detail="Board must include at least one chart")
    row = sqlite_store.update_board(
        board_id,
        title=body.title,
        question_text=body.question_text or body.title,
        chat_json=json.dumps(body.chat),
        charts_json=json.dumps([c.model_dump() for c in body.charts]),
        layout_json=json.dumps(body.layout),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Board not found")
    charts = json.loads(row["charts_json"] or "[]")
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "user_id": row.get("user_id"),
        "title": row["title"],
        "question_text": row["question_text"],
        "chart_count": len(charts) if isinstance(charts, list) else 0,
        "starred": bool(row.get("starred")),
        "created_at": row["created_at"],
    }


@router.get("/boards/{board_id}")
def get_board(board_id: str) -> dict[str, Any]:
    row = sqlite_store.get_board(board_id)
    if not row:
        raise HTTPException(status_code=404, detail="Board not found")
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "title": row["title"],
        "question_text": row["question_text"],
        "chat": json.loads(row["chat_json"] or "[]"),
        "charts": json.loads(row["charts_json"] or "[]"),
        "layout": json.loads(row["layout_json"] or "[]"),
        "starred": row["starred"],
        "created_at": row["created_at"],
    }


class BoardLayoutRequest(BaseModel):
    layout: list[dict[str, Any]]


@router.put("/boards/{board_id}/layout")
def save_board_layout(board_id: str, body: BoardLayoutRequest) -> dict[str, Any]:
    row = sqlite_store.update_board_layout(board_id, json.dumps(body.layout))
    if not row:
        raise HTTPException(status_code=404, detail="Board not found")
    return {"id": board_id, "layout": body.layout}


@router.post("/boards/{board_id}/star")
def star_board(board_id: str) -> dict[str, Any]:
    row = sqlite_store.toggle_board_star(board_id)
    if not row:
        raise HTTPException(status_code=404, detail="Board not found")
    return {"id": row["id"], "starred": row["starred"], "title": row["title"]}


@router.delete("/boards/{board_id}")
def remove_board(board_id: str) -> dict[str, Any]:
    if not sqlite_store.delete_board(board_id):
        raise HTTPException(status_code=404, detail="Board not found")
    return {"id": board_id, "deleted": True}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
