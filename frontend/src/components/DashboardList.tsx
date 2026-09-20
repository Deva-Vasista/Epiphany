"use client";

import { useEffect, useState } from "react";
import { Loader2, Star, Trash2 } from "lucide-react";
import {
  deleteBoard,
  listBoards,
  toggleBoardStar,
  type BoardSummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  userId: string | null;
  refreshKey: number;
  activeBoardId?: string | null;
  onOpenBoard: (id: string) => void;
};

export function DashboardList({
  userId,
  refreshKey,
  activeBoardId,
  onOpenBoard,
}: Props) {
  const [items, setItems] = useState<BoardSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) {
      setItems([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const rows = await listBoards(userId);
        if (!cancelled) {
          setItems(rows);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, refreshKey]);

  async function onStar(id: string) {
    try {
      const res = await toggleBoardStar(id);
      setItems((prev) =>
        prev
          .map((d) => (d.id === id ? { ...d, starred: res.starred } : d))
          .sort((a, b) => Number(b.starred) - Number(a.starred)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Star failed");
    }
  }

  async function onDelete(id: string) {
    if (busyId) return;
    setBusyId(id);
    try {
      await deleteBoard(id);
      setItems((prev) => prev.filter((d) => d.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-display text-xl text-[var(--ink)]">Saved dashboards</h2>
        <p className="text-sm text-[var(--muted)]">
          Available across all your sessions. Click to restore.
        </p>
      </div>

      {error && (
        <p className="bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      <ul className="space-y-1">
        {items.map((d) => (
          <li key={d.id}>
            <div
              className={cn(
                "flex w-full items-start gap-2 border-b border-[var(--line)] py-2",
                activeBoardId === d.id && "bg-[var(--accent-soft)]",
              )}
            >
              <button
                type="button"
                aria-label="Toggle star"
                onClick={() => void onStar(d.id)}
                className="mt-0.5"
              >
                <Star
                  className={cn(
                    "h-4 w-4",
                    d.starred
                      ? "fill-[var(--accent)] text-[var(--accent)]"
                      : "text-[var(--muted)]",
                  )}
                />
              </button>
              <button
                type="button"
                onClick={() => onOpenBoard(d.id)}
                className="min-w-0 flex-1 text-left"
              >
                <p className="truncate text-sm font-medium text-[var(--ink)]">
                  {d.title}
                </p>
                <p className="truncate text-xs text-[var(--muted)]">
                  {d.chart_count} chart{d.chart_count === 1 ? "" : "s"}
                  {d.question_text ? ` · ${d.question_text}` : ""}
                </p>
              </button>
              <button
                type="button"
                aria-label="Delete board"
                disabled={busyId === d.id}
                onClick={() => void onDelete(d.id)}
                className="mt-0.5 text-[var(--muted)] hover:text-red-700"
              >
                {busyId === d.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
              </button>
            </div>
          </li>
        ))}
        {userId && items.length === 0 && (
          <li className="text-sm text-[var(--muted)]">
            No saved dashboards yet — populate the canvas, then Save dashboard.
          </li>
        )}
      </ul>
    </section>
  );
}
