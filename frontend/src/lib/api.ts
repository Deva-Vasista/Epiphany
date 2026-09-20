const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type FileSchema = {
  table_name: string;
  row_count: number;
  column_count: number;
  columns: Array<{
    name: string;
    dtype: string;
    null_pct: number;
    cardinality: number | null;
    sample_values: string[];
  }>;
  sample_rows: Record<string, unknown>[];
};

export type UploadedFile = {
  id: string;
  filename: string;
  duckdb_table_name: string;
  schema: FileSchema;
  created_at: string;
};

export type CanvasChart = {
  id: string;
  title: string;
  chart_type?: string | null;
  vega_lite_spec: Record<string, unknown>;
  question_text?: string;
};

export type SessionSummary = {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type SessionDetail = SessionSummary & {
  chat: unknown[];
  charts: CanvasChart[];
  layout: Array<Record<string, unknown>>;
};

export type BoardSummary = {
  id: string;
  session_id: string;
  title: string;
  question_text: string;
  chart_count: number;
  starred: boolean;
  created_at: string;
};

export type BoardDetail = {
  id: string;
  session_id: string;
  title: string;
  question_text: string;
  chat: unknown[];
  charts: CanvasChart[];
  layout: Array<Record<string, unknown>>;
  starred: boolean;
  created_at: string;
};

export type SseHandler = (event: string, data: Record<string, unknown>) => void;

export async function ensureUser(userId: string): Promise<string> {
  const res = await fetch(`${API_URL}/users/${encodeURIComponent(userId)}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
  const body = await res.json();
  return body.user_id as string;
}

export async function listSessions(userId: string): Promise<SessionSummary[]> {
  const res = await fetch(
    `${API_URL}/users/${encodeURIComponent(userId)}/sessions`,
  );
  if (!res.ok) throw new Error(await res.text());
  const body = await res.json();
  return body.sessions as SessionSummary[];
}

export async function createSession(
  userId: string,
  title?: string,
): Promise<SessionSummary> {
  const res = await fetch(`${API_URL}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, title }),
  });
  if (!res.ok) throw new Error(await res.text());
  const body = await res.json();
  return {
    id: body.session_id,
    user_id: body.user_id,
    title: body.title,
    created_at: body.created_at,
    updated_at: body.updated_at,
  };
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}`);
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as SessionDetail;
}

export async function renameSession(
  sessionId: string,
  title: string,
): Promise<SessionDetail> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as SessionDetail;
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function saveSessionChat(
  sessionId: string,
  chat: unknown[],
): Promise<void> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}/chat`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function saveSessionCanvas(
  sessionId: string,
  charts: CanvasChart[],
  layout: Array<Record<string, unknown>>,
): Promise<void> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}/canvas`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ charts, layout }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function uploadFiles(
  sessionId: string,
  files: FileList | File[],
): Promise<UploadedFile[]> {
  const form = new FormData();
  Array.from(files).forEach((f) => form.append("files", f));
  const res = await fetch(`${API_URL}/sessions/${sessionId}/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  const body = await res.json();
  return body.files as UploadedFile[];
}

export async function listFiles(sessionId: string): Promise<UploadedFile[]> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}/files`);
  if (!res.ok) throw new Error(await res.text());
  const body = await res.json();
  return body.files as UploadedFile[];
}

export async function listBoards(userId: string): Promise<BoardSummary[]> {
  const res = await fetch(
    `${API_URL}/users/${encodeURIComponent(userId)}/boards`,
  );
  if (!res.ok) throw new Error(await res.text());
  const body = await res.json();
  return body.boards as BoardSummary[];
}

export async function getBoard(id: string): Promise<BoardDetail> {
  const res = await fetch(`${API_URL}/boards/${id}`);
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as BoardDetail;
}

export async function saveBoard(
  sessionId: string,
  payload: {
    title: string;
    question_text?: string;
    chat: unknown[];
    charts: CanvasChart[];
    layout: Array<Record<string, unknown>>;
  },
): Promise<BoardSummary> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}/boards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as BoardSummary;
}

export async function updateBoard(
  boardId: string,
  payload: {
    title: string;
    question_text?: string;
    chat: unknown[];
    charts: CanvasChart[];
    layout: Array<Record<string, unknown>>;
  },
): Promise<BoardSummary> {
  const res = await fetch(`${API_URL}/boards/${boardId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as BoardSummary;
}

export async function updateBoardLayout(
  id: string,
  layout: Array<Record<string, unknown>>,
): Promise<void> {
  const res = await fetch(`${API_URL}/boards/${id}/layout`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ layout }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function toggleBoardStar(
  id: string,
): Promise<{ id: string; starred: boolean; title: string }> {
  const res = await fetch(`${API_URL}/boards/${id}/star`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

export async function deleteBoard(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/boards/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}

export async function streamChat(
  sessionId: string,
  message: string,
  saveDashboard: boolean,
  onEvent: SseHandler,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message, save_dashboard: saveDashboard }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(await res.text());
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const lines = part.split("\n");
      let event = "message";
      let data = "";
      for (const line of lines) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      try {
        onEvent(event, JSON.parse(data));
      } catch {
        onEvent(event, { raw: data });
      }
    }
  }
}
