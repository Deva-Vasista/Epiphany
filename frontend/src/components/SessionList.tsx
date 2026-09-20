"use client";

import { Plus, Trash2 } from "lucide-react";
import type { SessionSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
};

function formatWhen(iso: string) {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso.slice(0, 16);
  }
}

export function SessionList({
  sessions,
  activeSessionId,
  onSelect,
  onCreate,
  onDelete,
}: Props) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="font-display text-xl text-[var(--ink)]">Sessions</h2>
          <p className="text-sm text-[var(--muted)]">Your workspaces</p>
        </div>
        <button
          type="button"
          onClick={onCreate}
          className="inline-flex items-center gap-1 text-xs text-[var(--accent)]"
        >
          <Plus className="h-3.5 w-3.5" />
          New
        </button>
      </div>

      <ul className="space-y-1">
        {sessions.map((s) => (
          <li key={s.id}>
            <div
              className={cn(
                "flex items-start gap-2 border-b border-[var(--line)] py-2",
                activeSessionId === s.id && "bg-[var(--accent-soft)]",
              )}
            >
              <button
                type="button"
                onClick={() => onSelect(s.id)}
                className="min-w-0 flex-1 text-left"
              >
                <p className="truncate text-sm font-medium text-[var(--ink)]">
                  {s.title}
                </p>
                <p className="truncate text-[10px] text-[var(--muted)]">
                  {formatWhen(s.created_at)}
                </p>
              </button>
              <button
                type="button"
                aria-label="Delete session"
                onClick={() => onDelete(s.id)}
                className="mt-0.5 text-[var(--muted)] hover:text-red-700"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </li>
        ))}
        {sessions.length === 0 && (
          <li className="text-sm text-[var(--muted)]">No sessions yet.</li>
        )}
      </ul>
    </section>
  );
}
