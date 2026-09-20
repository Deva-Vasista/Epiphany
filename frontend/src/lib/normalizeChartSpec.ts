/**
 * Fix misleading scales (e.g. Year axis from 0→2200) and upgrade dual-series charts.
 */
export function normalizeChartSpec(
  spec: Record<string, unknown>,
): Record<string, unknown> {
  const next = fixAxes(ensureSizing({ ...spec }));

  if (
    next.layer ||
    (next.resolve as { scale?: { y?: string } } | undefined)?.scale?.y ===
      "independent"
  ) {
    return next;
  }

  const data = (next.data as { values?: Record<string, unknown>[] } | undefined)
    ?.values;
  const encoding = next.encoding as
    | Record<string, { field?: string; type?: string; scale?: unknown; axis?: unknown }>
    | undefined;
  if (
    !data?.length ||
    !encoding?.x?.field ||
    !encoding?.y?.field ||
    !encoding?.color?.field
  ) {
    return next;
  }

  const xField = encoding.x.field;
  const yField = encoding.y.field;
  const colorField = encoding.color.field;

  const series = new Map<string, number[]>();
  for (const row of data) {
    const key = String(row[colorField] ?? "");
    const raw = row[yField];
    const n = typeof raw === "number" ? raw : Number(raw);
    if (!Number.isFinite(n)) continue;
    if (!series.has(key)) series.set(key, []);
    series.get(key)!.push(n);
  }

  const keys = [...series.keys()].filter(Boolean);
  if (keys.length < 2) return next;

  const ranges = keys.map((k) => {
    const vals = series.get(k)!;
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const mid = (min + max) / 2 || 1;
    return { key: k, mid };
  });

  const mids = ranges.map((r) => Math.abs(r.mid)).sort((a, b) => a - b);
  const ratio = mids[mids.length - 1] / Math.max(mids[0], 1e-9);
  if (ratio < 3) return next;

  const palette = ["#0f766e", "#c2410c", "#1d4ed8", "#7c3aed", "#b45309"];
  const xEnc = fixChannel(encoding.x, data, xField);
  const layers = ranges.map((r, i) => ({
    transform: [
      { filter: `datum['${colorField}'] === '${r.key.replace(/'/g, "\\'")}'` },
    ],
    mark: {
      type: (next.mark as { type?: string })?.type ?? "line",
      tooltip: true,
    },
    encoding: {
      x: xEnc,
      y: {
        field: yField,
        type: "quantitative",
        title: r.key,
        scale: { zero: false },
        axis: {
          orient: i === 0 ? "left" : "right",
          titleColor: palette[i % palette.length],
        },
      },
      color: { value: palette[i % palette.length] },
    },
  }));

  const rest = { ...next };
  delete rest.encoding;
  delete rest.mark;
  return ensureSizing({
    ...rest,
    layer: layers,
    resolve: { scale: { y: "independent" } },
  });
}

function looksLikeYear(nums: number[]): boolean {
  if (!nums.length) return false;
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  if (lo < 1800 || hi > 2100 || hi - lo > 400) return false;
  return nums.slice(0, 50).every((v) => Math.abs(v - Math.round(v)) < 1e-6);
}

function numericField(
  data: Record<string, unknown>[],
  field: string,
): number[] {
  const out: number[] = [];
  for (const row of data) {
    const raw = row[field];
    const n = typeof raw === "number" ? raw : Number(raw);
    if (Number.isFinite(n)) out.push(n);
  }
  return out;
}

function fixChannel(
  channel: { field?: string; type?: string; scale?: unknown; axis?: unknown },
  data: Record<string, unknown>[],
  field: string,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...channel, field, title: field };
  const nums = numericField(data, field);
  if (!nums.length) return next;

  if (looksLikeYear(nums)) {
    const distinct = [...new Set(nums.map((v) => Math.round(v)))].sort(
      (a, b) => a - b,
    );
    if (distinct.length >= 8) {
      next.type = "quantitative";
      next.scale = {
        zero: false,
        nice: false,
        domain: [distinct[0], distinct[distinct.length - 1]],
      };
      next.axis = { format: "d", tickCount: Math.min(10, distinct.length) };
    } else {
      next.type = "ordinal";
      next.axis = { labelAngle: 0 };
      delete next.scale;
    }
  } else if (next.type === "quantitative" || nums.length) {
    next.type = next.type ?? "quantitative";
    next.scale = { ...(next.scale as object), zero: false, nice: true };
    const lo = Math.min(...nums);
    const hi = Math.max(...nums);
    if (lo >= 1000 && hi < 10000 && hi - lo < 500) {
      next.axis = { ...(next.axis as object), format: "d" };
    }
  }
  return next;
}

function fixAxes(spec: Record<string, unknown>): Record<string, unknown> {
  const data = (spec.data as { values?: Record<string, unknown>[] } | undefined)
    ?.values;
  if (!data?.length) return spec;

  if (Array.isArray(spec.layer)) {
    return {
      ...spec,
      layer: (spec.layer as Record<string, unknown>[]).map((layer) => {
        const enc = layer.encoding as
          | Record<string, { field?: string; type?: string }>
          | undefined;
        if (!enc) return layer;
        const fixed: Record<string, unknown> = { ...enc };
        if (enc.x?.field) fixed.x = fixChannel(enc.x, data, enc.x.field);
        if (enc.y?.field) fixed.y = fixChannel(enc.y, data, enc.y.field);
        return { ...layer, encoding: fixed };
      }),
    };
  }

  const encoding = spec.encoding as
    | Record<string, { field?: string; type?: string }>
    | undefined;
  if (!encoding) return spec;
  const fixed: Record<string, unknown> = { ...encoding };
  if (encoding.x?.field) fixed.x = fixChannel(encoding.x, data, encoding.x.field);
  if (encoding.y?.field) fixed.y = fixChannel(encoding.y, data, encoding.y.field);
  return { ...spec, encoding: fixed };
}

function ensureSizing(spec: Record<string, unknown>): Record<string, unknown> {
  return {
    ...spec,
    width: spec.width ?? "container",
    height: spec.height ?? 320,
  };
}
