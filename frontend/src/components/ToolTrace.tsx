"use client";

import { useMemo, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  Database,
  LineChart,
  Loader2,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type TraceItem = {
  id: string;
  kind: "status" | "tool_start" | "tool_result" | "forecast_meta" | "error";
  tool?: string;
  title: string;
  detail?: string;
  status?: "pending" | "done" | "error";
};

type Step = {
  id: string;
  tool: string;
  label: string;
  status: "pending" | "done" | "error";
  detail?: string;
};

const TOOL_LABELS: Record<string, string> = {
  status: "Thinking",
  query_data: "Querying data",
  forecast: "Forecasting",
  render_chart: "Rendering chart",
};

function labelFor(tool: string) {
  return TOOL_LABELS[tool] ?? tool.replace(/_/g, " ");
}

function iconFor(tool: string, status: Step["status"]) {
  const cls = "h-3.5 w-3.5 shrink-0";
  if (status === "pending") return <Loader2 className={cn(cls, "animate-spin text-[var(--accent)]")} />;
  if (status === "error") return <AlertCircle className={cn(cls, "text-red-600")} />;
  if (tool === "query_data") return <Database className={cn(cls, "text-[var(--accent)]")} />;
  if (tool === "forecast") return <TrendingUp className={cn(cls, "text-[var(--accent)]")} />;
  if (tool === "render_chart") return <LineChart className={cn(cls, "text-[var(--accent)]")} />;
  if (tool === "status") return <Sparkles className={cn(cls, "text-[var(--accent)]")} />;
  return <Check className={cn(cls, "text-[var(--accent)]")} />;
}

/** Collapse raw SSE trace items into compact stepper steps. */
export function buildSteps(items: TraceItem[]): Step[] {
  const steps: Step[] = [];
  const open = new Map<string, number>();

  for (const item of items) {
    if (item.kind === "status") {
      steps.push({
        id: item.id,
        tool: "status",
        label: labelFor("status"),
        status: item.status ?? "done",
        detail: item.detail,
      });
      continue;
    }
    if (item.kind === "tool_start") {
      const tool = item.tool ?? "tool";
      const step: Step = {
        id: item.id,
        tool,
        label: labelFor(tool),
        status: "pending",
        detail: item.detail,
      };
      open.set(tool, steps.length);
      steps.push(step);
      continue;
    }
    if (item.kind === "tool_result") {
      const tool = item.tool ?? "tool";
      const idx = open.get(tool);
      let isErr = false;
      if (item.detail) {
        try {
          const parsed = JSON.parse(item.detail.split("\n\n--- result ---\n\n").pop() || item.detail);
          isErr = Boolean(parsed && typeof parsed === "object" && parsed.error);
        } catch {
          isErr = false;
        }
      }
      if (idx !== undefined) {
        const prev = steps[idx];
        steps[idx] = {
          ...prev,
          status: isErr ? "error" : "done",
          detail: [prev.detail, item.detail].filter(Boolean).join("\n\n--- result ---\n\n"),
        };
        open.delete(tool);
      } else {
        steps.push({
          id: item.id,
          tool,
          label: labelFor(tool),
          status: isErr ? "error" : "done",
          detail: item.detail,
        });
      }
      continue;
    }
    if (item.kind === "error") {
      steps.push({
        id: item.id,
        tool: "error",
        label: "Error",
        status: "error",
        detail: item.detail,
      });
    }
  }
  return steps;
}

type Props = {
  items: TraceItem[];
  live?: boolean;
};

export function ToolTrace({ items, live }: Props) {
  const steps = useMemo(() => buildSteps(items), [items]);
  const [openId, setOpenId] = useState<string | null>(null);

  if (!steps.length) return null;

  return (
    <ol className="space-y-1 rounded-md border border-[var(--line)] bg-[var(--paper)]/50 px-2 py-1.5">
      {steps.map((step) => {
        const expanded = openId === step.id;
        const hasDetail = Boolean(step.detail);
        return (
          <li key={step.id}>
            <button
              type="button"
              disabled={!hasDetail}
              onClick={() => setOpenId(expanded ? null : step.id)}
              className={cn(
                "flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs transition",
                hasDetail && "hover:bg-[var(--accent-soft)]",
                !hasDetail && "cursor-default",
              )}
            >
              {iconFor(step.tool, live && step.status === "pending" ? "pending" : step.status)}
              <span className="flex-1 font-medium text-[var(--ink)]">{step.label}</span>
              <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
                {step.status === "pending" ? "…" : step.status}
              </span>
              {hasDetail && (
                <ChevronDown
                  className={cn(
                    "h-3.5 w-3.5 text-[var(--muted)] transition",
                    expanded && "rotate-180",
                  )}
                />
              )}
            </button>
            {expanded && step.detail && (
              <pre className="mb-1 max-h-36 overflow-auto whitespace-pre-wrap rounded bg-white/70 px-2 py-1.5 font-mono text-[10px] leading-relaxed text-[var(--ink)]/75">
                {step.detail}
              </pre>
            )}
          </li>
        );
      })}
    </ol>
  );
}
