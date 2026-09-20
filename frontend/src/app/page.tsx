"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Layout } from "react-grid-layout";
import {
  createSession,
  deleteSession,
  ensureUser,
  getBoard,
  getSession,
  listFiles,
  listSessions,
  renameSession,
  saveBoard,
  saveSessionCanvas,
  saveSessionChat,
  updateBoard,
  updateBoardLayout,
  type CanvasChart,
  type SessionSummary,
  type UploadedFile,
} from "@/lib/api";
import { UploadPanel } from "@/components/UploadPanel";
import {
  ChatPanel,
  type ChatMessage,
  type ChatPanelHandle,
} from "@/components/ChatPanel";
import { DashboardList } from "@/components/DashboardList";
import { DashboardCanvas } from "@/components/DashboardCanvas";
import { SessionList } from "@/components/SessionList";
import { cn } from "@/lib/utils";

const USER_KEY = "epiphany_user_id";
const SESSION_KEY = "epiphany_session_id";

function getOrCreateUserId(): string {
  if (typeof window === "undefined") return "";
  let id = localStorage.getItem(USER_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(USER_KEY, id);
  }
  return id;
}

export default function HomePage() {
  const [userId, setUserId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [bootError, setBootError] = useState<string | null>(null);
  const [boardKey, setBoardKey] = useState(0);
  const [booting, setBooting] = useState(true);
  const [canvasCharts, setCanvasCharts] = useState<CanvasChart[]>([]);
  const [layout, setLayout] = useState<Layout[]>([]);
  const [saving, setSaving] = useState(false);
  const [activeBoardId, setActiveBoardId] = useState<string | null>(null);
  const [activeBoardTitle, setActiveBoardTitle] = useState<string | null>(null);
  const [chatSeed, setChatSeed] = useState<ChatMessage[]>([]);
  const chatRef = useRef<ChatPanelHandle>(null);
  const persistTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshSessions = useCallback(async (uid: string) => {
    const rows = await listSessions(uid);
    setSessions(rows);
    return rows;
  }, []);

  const loadSession = useCallback(async (sid: string) => {
    const detail = await getSession(sid);
    setSessionId(detail.id);
    localStorage.setItem(SESSION_KEY, detail.id);
    const chat = (detail.chat || []) as ChatMessage[];
    setChatSeed(chat);
    chatRef.current?.loadMessages(chat);
    setCanvasCharts(detail.charts || []);
    setLayout((detail.layout || []) as unknown as Layout[]);
    setActiveBoardId(null);
    setActiveBoardTitle(null);
    setBoardKey((k) => k + 1);
    try {
      const existingFiles = await listFiles(detail.id);
      setFiles(existingFiles);
    } catch {
      setFiles([]);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const bootTimeout = window.setTimeout(() => {
      if (!cancelled) {
        setBootError((prev) => prev ?? "Startup is taking too long — is the API running on port 8000?");
        setBooting(false);
      }
    }, 20000);

    (async () => {
      try {
        const uid = getOrCreateUserId();
        await ensureUser(uid);
        if (cancelled) return;
        setUserId(uid);

        let rows = await refreshSessions(uid);
        let sid = localStorage.getItem(SESSION_KEY);
        if (!sid || !rows.some((r) => r.id === sid)) {
          if (rows.length === 0) {
            const created = await createSession(uid, "My first session");
            rows = await refreshSessions(uid);
            sid = created.id;
          } else {
            sid = rows[0].id;
          }
        }
        if (cancelled || !sid) return;
        await loadSession(sid);
        if (!cancelled) await refreshSessions(uid);
      } catch (err) {
        if (!cancelled) {
          setBootError(
            err instanceof Error
              ? err.message
              : "Could not reach the server. Is it running?",
          );
        }
      } finally {
        window.clearTimeout(bootTimeout);
        if (!cancelled) setBooting(false);
      }
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(bootTimeout);
    };
  }, [loadSession, refreshSessions]);

  async function handleNewSession() {
    if (!userId) return;
    try {
      const created = await createSession(userId);
      await refreshSessions(userId);
      await loadSession(created.id);
    } catch (err) {
      setBootError(err instanceof Error ? err.message : "Failed to create session");
    }
  }

  async function handleSelectSession(id: string) {
    if (id === sessionId) return;
    // Persist current canvas before switching
    if (sessionId) {
      try {
        await saveSessionCanvas(
          sessionId,
          canvasCharts,
          layout as unknown as Array<Record<string, unknown>>,
        );
        const msgs = chatRef.current?.getMessages() ?? [];
        await saveSessionChat(sessionId, msgs);
      } catch {
        // continue switch even if persist fails
      }
    }
    try {
      await loadSession(id);
    } catch (err) {
      setBootError(err instanceof Error ? err.message : "Failed to open session");
    }
  }

  async function handleDeleteSession(id: string) {
    if (!userId) return;
    try {
      await deleteSession(id);
      const rows = await refreshSessions(userId);
      if (id === sessionId) {
        if (rows.length) {
          await loadSession(rows[0].id);
        } else {
          const created = await createSession(userId);
          await refreshSessions(userId);
          await loadSession(created.id);
        }
      }
    } catch (err) {
      setBootError(err instanceof Error ? err.message : "Failed to delete session");
    }
  }

  function persistChat(msgs: ChatMessage[]) {
    if (!sessionId) return;
    if (persistTimer.current) clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(() => {
      void saveSessionChat(sessionId, msgs);
      // Name the session after the first user question
      const firstUser = msgs.find((m) => m.role === "user");
      const current = sessions.find((s) => s.id === sessionId);
      if (
        firstUser &&
        current &&
        (/^Session\b/i.test(current.title) ||
          /^My first session$/i.test(current.title) ||
          /^Untitled/i.test(current.title))
      ) {
        const title = firstUser.text.slice(0, 60).trim() || current.title;
        void renameSession(sessionId, title).then(() => {
          if (userId) void refreshSessions(userId);
        });
      }
    }, 400);
  }

  function persistCanvas(charts: CanvasChart[], nextLayout: Layout[]) {
    if (!sessionId) return;
    void saveSessionCanvas(
      sessionId,
      charts,
      nextLayout as unknown as Array<Record<string, unknown>>,
    );
  }

  function handleCanvasChart(chart: CanvasChart) {
    setCanvasCharts((prev) => {
      if (prev.some((c) => c.id === chart.id)) return prev;
      const next = [...prev, chart];
      persistCanvas(next, layout);
      // Keep editing the same saved board — auto-update if one is active
      if (activeBoardId && sessionId) {
        const msgs = chatRef.current?.getMessages() ?? [];
        const title =
          activeBoardTitle ||
          next[0]?.question_text?.slice(0, 80) ||
          `Dashboard · ${next.length} charts`;
        void updateBoard(activeBoardId, {
          title,
          question_text: next[0]?.question_text || title,
          chat: msgs,
          charts: next,
          layout: layout as unknown as Array<Record<string, unknown>>,
        }).then(() => setBoardKey((k) => k + 1));
      }
      return next;
    });
  }

  async function handleSaveBoard() {
    if (!sessionId || !canvasCharts.length || saving) return;
    setSaving(true);
    try {
      const msgs = chatRef.current?.getMessages() ?? [];
      const title =
        activeBoardTitle ||
        canvasCharts[0]?.question_text?.slice(0, 80) ||
        `Dashboard · ${canvasCharts.length} charts`;
      const payload = {
        title,
        question_text: canvasCharts[0]?.question_text || title,
        chat: msgs,
        charts: canvasCharts,
        layout: layout as unknown as Array<Record<string, unknown>>,
      };
      const saved = activeBoardId
        ? await updateBoard(activeBoardId, payload)
        : await saveBoard(sessionId, payload);
      setActiveBoardId(saved.id);
      setActiveBoardTitle(saved.title);
      setBoardKey((k) => k + 1);
    } catch (err) {
      setBootError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleOpenBoard(id: string) {
    try {
      const board = await getBoard(id);
      const charts = board.charts;
      const nextLayout = (board.layout || []) as unknown as Layout[];
      setCanvasCharts(charts);
      setLayout(nextLayout);
      setActiveBoardId(board.id);
      setActiveBoardTitle(board.title);
      const chat = (board.chat || []) as ChatMessage[];
      setChatSeed(chat);
      chatRef.current?.loadMessages(chat);
      if (sessionId) {
        void saveSessionChat(sessionId, chat);
        void saveSessionCanvas(
          sessionId,
          charts,
          nextLayout as unknown as Array<Record<string, unknown>>,
        );
      }
    } catch (err) {
      setBootError(err instanceof Error ? err.message : "Failed to open board");
    }
  }

  function handleLayoutChange(next: Layout[]) {
    setLayout(next);
    persistCanvas(canvasCharts, next);
    if (activeBoardId) {
      void updateBoardLayout(
        activeBoardId,
        next as unknown as Array<Record<string, unknown>>,
      );
    }
  }

  function handleRemoveChart(id: string) {
    setCanvasCharts((prev) => {
      const next = prev.filter((c) => c.id !== id);
      persistCanvas(next, layout);
      if (activeBoardId && sessionId && next.length > 0) {
        const msgs = chatRef.current?.getMessages() ?? [];
        const title =
          activeBoardTitle ||
          next[0]?.question_text?.slice(0, 80) ||
          `Dashboard · ${next.length} charts`;
        void updateBoard(activeBoardId, {
          title,
          question_text: next[0]?.question_text || title,
          chat: msgs,
          charts: next,
          layout: layout as unknown as Array<Record<string, unknown>>,
        }).then(() => setBoardKey((k) => k + 1));
      }
      return next;
    });
  }

  const showDashboard = canvasCharts.length > 0;

  return (
    <div className="relative flex h-screen flex-col overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-40" aria-hidden />

      <header className="relative z-10 mx-auto flex w-full max-w-[1600px] shrink-0 items-end justify-between gap-6 px-4 pb-4 pt-8 md:px-6">
        <div>
          <h1 className="font-display text-4xl tracking-tight text-[var(--ink)] md:text-5xl">
            Epiphany
          </h1>
          <p className="mt-2 max-w-lg text-sm leading-relaxed text-[var(--muted)]">
            Upload your spreadsheets, ask questions in plain English, and explore
            charts. Save dashboards and switch between sessions anytime.
          </p>
        </div>
        <p className="font-mono text-[10px] text-[var(--muted)]">
          {booting ? "Starting…" : ""}
        </p>
      </header>

      {bootError && (
        <div className="relative z-10 mx-auto w-full max-w-[1600px] shrink-0 px-4 md:px-6">
          <p className="mb-3 bg-red-50 px-4 py-2 text-sm text-red-800">{bootError}</p>
        </div>
      )}

      <main
        className={cn(
          "relative z-10 mx-auto grid min-h-0 w-full max-w-[1600px] flex-1 gap-4 overflow-hidden px-4 pb-4 md:px-6",
          "grid-cols-1 lg:grid-cols-[minmax(200px,240px)_minmax(0,1fr)]",
          showDashboard &&
            "xl:grid-cols-[minmax(200px,240px)_minmax(0,1fr)_minmax(360px,1.2fr)]",
        )}
      >
        <div className="min-h-0 space-y-6 overflow-y-auto">
          <SessionList
            sessions={sessions}
            activeSessionId={sessionId}
            onSelect={(id) => void handleSelectSession(id)}
            onCreate={() => void handleNewSession()}
            onDelete={(id) => void handleDeleteSession(id)}
          />
          <UploadPanel
            sessionId={sessionId}
            files={files}
            onUploaded={(uploaded) =>
              setFiles((prev) => {
                const map = new Map(prev.map((f) => [f.id, f]));
                uploaded.forEach((f) => map.set(f.id, f));
                return Array.from(map.values());
              })
            }
          />
          <DashboardList
            userId={userId}
            refreshKey={boardKey}
            activeBoardId={activeBoardId}
            onOpenBoard={(id) => void handleOpenBoard(id)}
          />
        </div>

        <div className="flex min-h-0 flex-col border border-[var(--line)] bg-[var(--panel)]/80 p-4">
          <h2 className="font-display mb-3 shrink-0 text-xl text-[var(--ink)]">Ask</h2>
          <div className="min-h-0 flex-1">
            <ChatPanel
              ref={chatRef}
              sessionId={sessionId}
              seedMessages={chatSeed}
              disabled={files.length === 0}
              onCanvasChart={handleCanvasChart}
              onMessagesChange={persistChat}
            />
          </div>
        </div>

        {showDashboard && (
          <div className="min-h-0">
            <DashboardCanvas
              charts={canvasCharts}
              layout={layout}
              onLayoutChange={handleLayoutChange}
              onRemoveChart={handleRemoveChart}
              onSaveBoard={() => void handleSaveBoard()}
              saving={saving}
              activeBoardTitle={activeBoardTitle}
            />
          </div>
        )}
      </main>
    </div>
  );
}
