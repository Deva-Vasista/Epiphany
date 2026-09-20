"""Vega-Lite chart rendering with encoding validation."""

from __future__ import annotations

from typing import Any


ALLOWED_MARKS = {"bar", "line", "point", "area"}
PALETTE = ["#0f766e", "#c2410c", "#1d4ed8", "#7c3aed", "#b45309"]


def _infer_column_kinds(data: list[dict[str, Any]]) -> dict[str, str]:
    """Return mapping column -> temporal | quantitative | nominal."""
    if not data:
        return {}
    keys = set()
    for row in data:
        keys.update(row.keys())
    kinds: dict[str, str] = {}
    for key in keys:
        values = [row.get(key) for row in data if row.get(key) is not None]
        if not values:
            kinds[key] = "nominal"
            continue
        temporal_hits = 0
        numeric_hits = 0
        for v in values[:50]:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric_hits += 1
            elif isinstance(v, str):
                if len(v) >= 8 and ("-" in v or "/" in v) and any(c.isdigit() for c in v):
                    try:
                        import pandas as pd

                        parsed = pd.to_datetime(v, errors="coerce")
                        if parsed is not pd.NaT and not isinstance(parsed, float):
                            temporal_hits += 1
                    except Exception:
                        pass
                else:
                    try:
                        float(v)
                        numeric_hits += 1
                    except Exception:
                        pass
            elif hasattr(v, "isoformat"):
                temporal_hits += 1
        n = max(len(values[:50]), 1)
        if temporal_hits / n >= 0.6:
            kinds[key] = "temporal"
        elif numeric_hits / n >= 0.6:
            kinds[key] = "quantitative"
        else:
            kinds[key] = "nominal"
    return kinds


def _default_encoding(kinds: dict[str, str]) -> tuple[str, dict[str, str]]:
    temporal = [c for c, k in kinds.items() if k == "temporal"]
    quant = [c for c, k in kinds.items() if k == "quantitative"]
    nominal = [c for c, k in kinds.items() if k == "nominal"]

    if temporal and quant:
        enc: dict[str, str] = {"x": temporal[0], "y": quant[0]}
        if nominal:
            enc["color"] = nominal[0]
        return "line", enc
    if nominal and quant:
        return "bar", {"x": nominal[0], "y": quant[0]}
    if len(quant) >= 2:
        return "point", {"x": quant[0], "y": quant[1]}
    if quant:
        col = quant[0]
        return "bar", {"x": col, "y": col}
    cols = list(kinds.keys())
    if len(cols) >= 2:
        return "bar", {"x": cols[0], "y": cols[1]}
    if cols:
        return "bar", {"x": cols[0], "y": cols[0]}
    return "bar", {"x": "x", "y": "y"}


def _validate_proposal(
    mark: str,
    encoding: dict[str, str],
    kinds: dict[str, str],
) -> tuple[bool, str]:
    if mark not in ALLOWED_MARKS:
        return False, f"mark '{mark}' not allowed"
    x = encoding.get("x")
    y = encoding.get("y")
    if not x or not y:
        return False, "x and y encodings required"
    if x not in kinds or y not in kinds:
        return False, "encoding references unknown columns"
    color = encoding.get("color")
    if color and color not in kinds:
        return False, "color references unknown column"
    if mark in {"line", "area"} and kinds.get(x) not in {"temporal", "quantitative"}:
        return False, "line/area x should be temporal or quantitative"
    if kinds.get(y) != "quantitative" and mark in {"line", "area", "bar", "point"}:
        if kinds.get(y) == "nominal" and kinds.get(x) == "nominal":
            return False, "both axes nominal"
    return True, "ok"


def _series_need_independent_axes(
    values: list[dict[str, Any]],
    y_field: str,
    color_field: str,
) -> tuple[bool, list[str]]:
    series: dict[str, list[float]] = {}
    for row in values:
        key = str(row.get(color_field, ""))
        raw = row.get(y_field)
        try:
            n = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        series.setdefault(key, []).append(n)

    keys = [k for k in series if k]
    if len(keys) < 2:
        return False, keys

    mids: list[float] = []
    for k in keys:
        vals = series[k]
        mid = (min(vals) + max(vals)) / 2.0
        mids.append(abs(mid) if mid != 0 else 1.0)
    mids.sort()
    ratio = mids[-1] / max(mids[0], 1e-9)
    return ratio >= 3.0, keys


def _numeric_values(values: list[dict[str, Any]], field: str) -> list[float]:
    out: list[float] = []
    for row in values:
        raw = row.get(field)
        try:
            n = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if n == n:  # not NaN
            out.append(n)
    return out


def _looks_like_year(values: list[float]) -> bool:
    if not values:
        return False
    # Calendar years (or close): tight range in 1800–2100, not starting near 0
    lo, hi = min(values), max(values)
    if lo < 1800 or hi > 2100:
        return False
    if hi - lo > 400:
        return False
    # All near-integers
    return all(abs(v - round(v)) < 1e-6 for v in values[:50])


def _encoding_channel(
    field: str,
    kind: str,
    values: list[dict[str, Any]],
    *,
    for_y: bool = False,
) -> dict[str, Any]:
    """Build a Vega-Lite encoding channel with honest scales/formats."""
    channel: dict[str, Any] = {
        "field": field,
        "type": kind,
        "title": field,
    }
    nums = _numeric_values(values, field) if kind in {"quantitative", "temporal"} else []

    if kind == "quantitative" and nums:
        if _looks_like_year(nums):
            channel["type"] = "ordinal"  # treat years as discrete categories → no 0→2200 axis
            # Prefer quantitative with tight domain if many distinct years for lines
            distinct = sorted(set(int(round(v)) for v in nums))
            if len(distinct) >= 8:
                channel["type"] = "quantitative"
                channel["scale"] = {"zero": False, "nice": False, "domain": [distinct[0], distinct[-1]]}
                channel["axis"] = {"format": "d", "tickCount": min(10, len(distinct))}
            else:
                channel["axis"] = {"labelAngle": 0}
        else:
            channel["scale"] = {"zero": False, "nice": True}
            if for_y:
                channel["scale"]["zero"] = False
            # Avoid thousand-separators looking like years (1,930)
            lo, hi = min(nums), max(nums)
            if 1000 <= lo and hi < 10000 and hi - lo < 500:
                channel["axis"] = {"format": "d"}
    elif kind == "temporal":
        channel["axis"] = {"format": "%Y"}

    return channel


def _layered_independent_spec(
    values: list[dict[str, Any]],
    mark: str,
    x_field: str,
    y_field: str,
    color_field: str,
    x_type: str,
    series_keys: list[str],
    title: str,
) -> dict[str, Any]:
    x_channel = _encoding_channel(x_field, x_type if x_type != "nominal" else "quantitative", values)
    layers = []
    for i, key in enumerate(series_keys):
        safe = key.replace("\\", "\\\\").replace("'", "\\'")
        y_channel = _encoding_channel(y_field, "quantitative", values, for_y=True)
        y_channel["title"] = key
        y_channel["axis"] = {
            **(y_channel.get("axis") or {}),
            "orient": "left" if i == 0 else "right",
            "titleColor": PALETTE[i % len(PALETTE)],
        }
        layers.append(
            {
                "transform": [{"filter": f"datum['{color_field}'] === '{safe}'"}],
                "mark": {"type": mark, "tooltip": True},
                "encoding": {
                    "x": x_channel,
                    "y": y_channel,
                    "color": {"value": PALETTE[i % len(PALETTE)]},
                },
            }
        )

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title or "Chart",
        "width": "container",
        "height": 320,
        "data": {"values": values},
        "layer": layers,
        "resolve": {"scale": {"y": "independent"}},
    }


def render_chart(
    data: list[dict[str, Any]],
    mark: str,
    encoding: dict[str, str],
    title: str,
) -> dict[str, Any]:
    if not data:
        return {"error": "empty_data", "message": "No data to chart"}

    values = data[:1000]
    kinds = _infer_column_kinds(values)

    proposed_mark = mark if mark in ALLOWED_MARKS else "bar"
    proposed_enc = {
        "x": encoding.get("x", ""),
        "y": encoding.get("y", ""),
    }
    if encoding.get("color"):
        proposed_enc["color"] = encoding["color"]

    ok, reason = _validate_proposal(proposed_mark, proposed_enc, kinds)
    corrected = False
    if not ok:
        proposed_mark, proposed_enc = _default_encoding(kinds)
        corrected = True

    # Dual-scale: long-form series with mismatched magnitudes → independent y
    color_field = proposed_enc.get("color")
    independent = False
    series_keys: list[str] = []
    if color_field and kinds.get(color_field) == "nominal":
        independent, series_keys = _series_need_independent_axes(
            values, proposed_enc["y"], color_field
        )

    if independent and color_field:
        spec = _layered_independent_spec(
            values=values,
            mark=proposed_mark if proposed_mark in {"line", "area", "point"} else "line",
            x_field=proposed_enc["x"],
            y_field=proposed_enc["y"],
            color_field=color_field,
            x_type=kinds.get(proposed_enc["x"], "quantitative"),
            series_keys=series_keys,
            title=title or "Chart",
        )
        return {
            "vega_lite_spec": spec,
            "mark": proposed_mark,
            "encoding": proposed_enc,
            "corrected": corrected,
            "correction_reason": None if not corrected else reason,
            "column_kinds": kinds,
            "title": title or "Chart",
            "independent_y": True,
        }

    vl_encoding: dict[str, Any] = {
        "x": _encoding_channel(
            proposed_enc["x"],
            kinds.get(proposed_enc["x"], "nominal"),
            values,
        ),
        "y": _encoding_channel(
            proposed_enc["y"],
            kinds.get(proposed_enc["y"], "quantitative"),
            values,
            for_y=True,
        ),
        "tooltip": [{"field": f, "type": kinds.get(f, "nominal")} for f in kinds],
    }

    if proposed_enc.get("color") and proposed_enc["color"] in kinds:
        vl_encoding["color"] = {
            "field": proposed_enc["color"],
            "type": kinds[proposed_enc["color"]],
        }

    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title or "Chart",
        "width": "container",
        "height": 320,
        "data": {"values": values},
        "mark": {"type": proposed_mark, "tooltip": True},
        "encoding": vl_encoding,
    }

    return {
        "vega_lite_spec": spec,
        "mark": proposed_mark,
        "encoding": proposed_enc,
        "corrected": corrected,
        "correction_reason": None if not corrected else reason,
        "column_kinds": kinds,
        "title": title or "Chart",
        "independent_y": False,
    }
