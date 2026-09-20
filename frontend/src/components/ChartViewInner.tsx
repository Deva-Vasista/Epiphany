"use client";

import { useMemo } from "react";
import { VegaEmbed } from "react-vega";
import { normalizeChartSpec } from "@/lib/normalizeChartSpec";

type Props = {
  spec: Record<string, unknown>;
  className?: string;
  height?: number;
};

export function ChartViewInner({ spec, className, height }: Props) {
  const safeSpec = useMemo(() => {
    const normalized = normalizeChartSpec(spec);
    if (height) normalized.height = height;
    return normalized;
  }, [spec, height]);

  return (
    <div
      className={
        className ?? "w-full overflow-x-auto rounded-lg bg-white/70 p-3"
      }
    >
      <VegaEmbed
        spec={safeSpec as never}
        options={{ actions: false, renderer: "canvas" }}
      />
    </div>
  );
}
