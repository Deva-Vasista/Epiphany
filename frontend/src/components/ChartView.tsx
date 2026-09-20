"use client";

import dynamic from "next/dynamic";

const ChartViewInner = dynamic(
  () => import("@/components/ChartViewInner").then((m) => m.ChartViewInner),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-32 items-center justify-center text-sm text-[var(--muted)]">
        Loading chart…
      </div>
    ),
  },
);

type Props = {
  spec: Record<string, unknown>;
  className?: string;
  height?: number;
};

export function ChartView(props: Props) {
  return <ChartViewInner {...props} />;
}
