"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import GridLayout, { type Layout } from "react-grid-layout";
import { Loader2, Save, Trash2 } from "lucide-react";
import type { CanvasChart } from "@/lib/api";
import { ChartView } from "@/components/ChartView";
import { cn } from "@/lib/utils";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

type Props = {
  charts: CanvasChart[];
  layout: Layout[];
  onLayoutChange: (layout: Layout[]) => void;
  onRemoveChart: (id: string) => void;
  onSaveBoard: () => void;
  saving?: boolean;
  activeBoardTitle?: string | null;
};

export function DashboardCanvas({
  charts,
  layout,
  onLayoutChange,
  onRemoveChart,
  onSaveBoard,
  saving,
  activeBoardTitle,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(Math.max(320, Math.floor(w)));
    });
    ro.observe(node);
    setWidth(Math.max(320, Math.floor(node.clientWidth)));
    return () => ro.disconnect();
  }, []);

  const effectiveLayout = useMemo(() => {
    if (!charts.length) return [];
    const byId = new Map(layout.map((l) => [l.i, l]));
    return charts.map((c, i) => {
      const existing = byId.get(c.id);
      if (existing) return existing;
      return {
        i: c.id,
        x: (i % 2) * 6,
        y: Math.floor(i / 2) * 8,
        w: 6,
        h: 8,
        minW: 3,
        minH: 5,
      } satisfies Layout;
    });
  }, [charts, layout]);

  return (
    <aside className="flex h-full min-h-0 flex-col border border-[var(--line)] bg-[var(--panel)]/80">
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--line)] px-4 py-3">
        <div>
          <h2 className="font-display text-lg text-[var(--ink)]">Dashboard</h2>
          <p className="text-xs text-[var(--muted)]">
            {activeBoardTitle
              ? `Loaded · ${activeBoardTitle}`
              : `${charts.length} live chart${charts.length === 1 ? "" : "s"} · drag handles to rearrange`}
          </p>
        </div>
        <button
          type="button"
          disabled={!charts.length || saving}
          onClick={onSaveBoard}
          className={cn(
            "inline-flex items-center gap-1.5 bg-[var(--accent)] px-3 py-1.5 text-xs text-white",
            (!charts.length || saving) && "opacity-40",
          )}
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          {activeBoardTitle ? "Update dashboard" : "Save dashboard"}
        </button>
      </header>

      <div ref={containerRef} className="min-h-0 flex-1 overflow-y-auto p-3">
        {charts.length === 0 && (
          <p className="text-sm text-[var(--muted)]">
            Charts from “visualize” / “build a dashboard” appear here. Drag the
            title bar to rearrange, then Save dashboard.
          </p>
        )}
        {charts.length > 0 && width > 0 && (
          <GridLayout
            className="layout"
            layout={effectiveLayout}
            cols={12}
            rowHeight={36}
            width={width}
            draggableHandle=".dash-drag-handle"
            onLayoutChange={(next) => onLayoutChange(next)}
            compactType="vertical"
          >
            {charts.map((c) => (
              <div
                key={c.id}
                className="dash-card overflow-hidden border border-[var(--line)] bg-white/80"
              >
                <div className="dash-drag-handle flex cursor-move items-start gap-2 border-b border-[var(--line)] bg-[var(--paper)]/80 px-2 py-1.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-[var(--ink)]">
                      {c.title}
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label="Remove chart"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemoveChart(c.id);
                    }}
                    className="text-[var(--muted)] hover:text-red-700"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="overflow-hidden p-1">
                  <ChartView
                    spec={c.vega_lite_spec}
                    height={200}
                    className="p-1"
                  />
                </div>
              </div>
            ))}
          </GridLayout>
        )}
      </div>
    </aside>
  );
}
