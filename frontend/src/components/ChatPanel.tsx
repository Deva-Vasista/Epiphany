"use client";

import { useEffect, useImperativeHandle, forwardRef, useState } from "react";
import { Loader2, Pin, Send } from "lucide-react";
import { streamChat, type CanvasChart } from "@/lib/api";
import { ChartView } from "@/components/ChartView";
import { Markdown } from "@/components/Markdown";
import { ToolTrace, type TraceItem } from "@/components/ToolTrace";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  charts: InlineChart[];
  question?: string;
  forecastMeta?: {
    frequency?: string;
    confidence?: string;
    method?: string;
    note?: string;
  };
  trace?: TraceItem[];
};

type InlineChart = {
  id: string;
  title: string;
  spec: Record<string, unknown>;
  autoSave: boolean;
};

export type ChatPanelHandle = {
  getMessages: () => ChatMessage[];
  loadMessages: (msgs: ChatMessage[]) => void;
};

type Props = {
  sessionId: string | null;
  disabled?: boolean;
  seedMessages?: ChatMessage[];
  onCanvasChart?: (chart: CanvasChart) => void;
  onMessagesChange?: (msgs: ChatMessage[]) => void;
};

export const ChatPanel = forwardRef<ChatPanelHandle, Props>(function ChatPanel(
  { sessionId, disabled, seedMessages, onCanvasChart, onMessagesChange },
  ref,
) {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>(seedMessages ?? []);
  const [liveTrace, setLiveTrace] = useState<TraceItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Reset chat when the active session changes
  useEffect(() => {
    setMessages(seedMessages ?? []);
    setLiveTrace([]);
    setError(null);
    setInput("");
    setBusy(false);
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  useImperativeHandle(ref, () => ({
    getMessages: () => messages,
    loadMessages: (msgs) => setMessages(msgs),
  }));

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!sessionId || !input.trim() || busy) return;

    const question = input.trim();
    setInput("");
    setError(null);
    setBusy(true);
    setLiveTrace([]);

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: question,
      charts: [],
    };
    setMessages((m) => {
      const next = [...m, userMsg];
      onMessagesChange?.(next);
      return next;
    });

    let answer = "";
    const charts: InlineChart[] = [];
    let forecastMeta: ChatMessage["forecastMeta"];
    const trace: TraceItem[] = [];

    try {
      await streamChat(sessionId, question, false, (event, data) => {
        if (event === "status") {
          trace.push({
            id: crypto.randomUUID(),
            kind: "status",
            tool: "status",
            title: "Thinking",
            detail: String(data.message ?? ""),
            status: "done",
          });
          setLiveTrace([...trace]);
        } else if (event === "tool_start") {
          const tool = String(data.tool ?? "tool");
          trace.push({
            id: crypto.randomUUID(),
            kind: "tool_start",
            tool,
            title: tool,
            detail: JSON.stringify(data.args ?? {}, null, 2),
            status: "pending",
          });
          setLiveTrace([...trace]);
        } else if (event === "tool_result") {
          const tool = String(data.tool ?? "tool");
          trace.push({
            id: crypto.randomUUID(),
            kind: "tool_result",
            tool,
            title: tool,
            detail: JSON.stringify(data.result ?? {}, null, 2),
            status: "done",
          });
          setLiveTrace([...trace]);
        } else if (event === "chart") {
          const autoSave = Boolean(data.auto_save);
          const chart: InlineChart = {
            id: crypto.randomUUID(),
            title: String(data.title ?? "Chart"),
            spec: data.vega_lite_spec as Record<string, unknown>,
            autoSave,
          };
          if (!autoSave) charts.push(chart);
        } else if (event === "canvas_chart") {
          onCanvasChart?.({
            id: String(data.id ?? crypto.randomUUID()),
            title: String(data.title ?? "Chart"),
            chart_type: (data.chart_type as string) ?? null,
            vega_lite_spec: data.vega_lite_spec as Record<string, unknown>,
            question_text: String(data.question_text ?? question),
          });
        } else if (event === "forecast_meta") {
          forecastMeta = {
            frequency: data.frequency as string | undefined,
            confidence: data.confidence as string | undefined,
            method: data.method as string | undefined,
            note: data.note as string | undefined,
          };
        } else if (event === "answer") {
          answer = String(data.text ?? "");
        } else if (event === "error") {
          setError(String(data.message ?? "Agent error"));
        }
      });

      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        text:
          answer.trim() ||
          "Analysis complete — see charts and tool results above.",
        charts: [...charts],
        question,
        forecastMeta,
        trace: [...trace],
      };
      setMessages((m) => {
        const next = [...m, assistantMsg];
        onMessagesChange?.(next);
        return next;
      });
      setLiveTrace([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed");
    } finally {
      setBusy(false);
    }
  }

  function addAdHocToCanvas(chart: InlineChart, question?: string) {
    onCanvasChart?.({
      id: chart.id,
      title: chart.title,
      vega_lite_spec: chart.spec,
      question_text: question,
    });
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto pr-1">
        {messages.length === 0 && !busy && (
          <div className="text-sm text-[var(--muted)]">
            Ask about totals, filters, trends — or “visualize the data” /
            “build a dashboard”.
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className="space-y-3">
            <div className="text-xs uppercase tracking-wide text-[var(--muted)]">
              {msg.role === "user" ? "You" : "Assistant"}
            </div>
            {msg.role === "user" ? (
              <p className="font-medium text-[var(--ink)]">{msg.text}</p>
            ) : (
              <>
                {/* Thinking / tool trace ABOVE the answer */}
                {msg.trace && msg.trace.length > 0 && (
                  <ToolTrace items={msg.trace} />
                )}
                <Markdown>{msg.text}</Markdown>
                {msg.forecastMeta && (
                  <p className="text-xs text-[var(--muted)]">
                    Forecast · freq {msg.forecastMeta.frequency ?? "?"} ·
                    confidence{" "}
                    <span className="text-[var(--accent)]">
                      {msg.forecastMeta.confidence ?? "?"}
                    </span>
                  </p>
                )}
                {msg.charts.map((chart) => (
                  <div
                    key={chart.id}
                    className="overflow-hidden border border-[var(--line)] bg-white/60"
                  >
                    <div className="flex items-center justify-between gap-2 border-b border-[var(--line)] px-3 py-2">
                      <p className="truncate text-sm font-medium text-[var(--ink)]">
                        {chart.title}
                      </p>
                      <button
                        type="button"
                        onClick={() => addAdHocToCanvas(chart, msg.question)}
                        className="inline-flex items-center gap-1.5 text-xs text-[var(--accent)]"
                      >
                        <Pin className="h-3.5 w-3.5" />
                        Add to dashboard
                      </button>
                    </div>
                    <ChartView spec={chart.spec} height={220} className="p-2" />
                  </div>
                ))}
              </>
            )}
          </div>
        ))}

        {busy && liveTrace.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-wide text-[var(--muted)]">
              Working
            </p>
            <ToolTrace items={liveTrace} live />
          </div>
        )}
      </div>

      {error && (
        <p className="mt-3 shrink-0 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <form
        onSubmit={onSubmit}
        className="mt-4 shrink-0 space-y-3 border-t border-[var(--line)] pt-4"
      >
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={!sessionId || disabled || busy}
            placeholder={
              disabled
                ? "Upload files first…"
                : "Ask a question about your data…"
            }
            className="min-w-0 flex-1 border border-[var(--line)] bg-[var(--paper)] px-3 py-2.5 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
          />
          <button
            type="submit"
            disabled={!sessionId || disabled || busy || !input.trim()}
            className="inline-flex items-center gap-2 bg-[var(--accent)] px-4 py-2.5 text-sm text-white disabled:opacity-40"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            Ask
          </button>
        </div>
      </form>
    </section>
  );
});
