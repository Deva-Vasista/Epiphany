"""Time-series forecast tool (statsmodels ETS / Holt-Winters)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing


def forecast(series: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    if not series:
        return {"error": "not_a_time_series", "reason": "empty series"}
    if horizon < 1 or horizon > 60:
        return {"error": "invalid_horizon", "reason": "horizon must be 1..60"}

    try:
        df = pd.DataFrame(series)
    except Exception as exc:
        return {"error": "not_a_time_series", "reason": f"invalid series payload: {exc}"}

    if "date" not in df.columns or "value" not in df.columns:
        return {
            "error": "not_a_time_series",
            "reason": "series items must have 'date' and 'value' keys",
        }

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if df["date"].isna().any():
        return {"error": "not_a_time_series", "reason": "unparseable dates"}

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    if df["value"].isna().all():
        return {"error": "not_a_time_series", "reason": "non-numeric values"}

    df = df.dropna(subset=["value"]).sort_values("date").drop_duplicates("date")
    df = df.set_index("date")

    if len(df) < 3:
        return {
            "error": "insufficient_history",
            "reason": "need at least 3 data points to forecast",
        }

    freq = pd.infer_freq(df.index)
    inferred = True
    if freq is None:
        inferred = False
        delta = df.index.to_series().diff().median()
        days = delta.days if hasattr(delta, "days") else 1
        if days <= 1:
            freq = "D"
        elif days <= 8:
            freq = "W"
        elif days <= 32:
            freq = "MS"
        elif days <= 95:
            freq = "QS"
        else:
            freq = "YS"
        try:
            df = df.asfreq(freq)
            df["value"] = df["value"].interpolate(limit_direction="both")
        except Exception:
            # keep irregular index; linear fallback later
            pass

    seasonal_map = {"D": 7, "W": 52, "MS": 12, "M": 12, "QS": 4, "Q": 4, "YS": 1, "Y": 1, "A": 1}
    # Normalize freq key (e.g. W-SUN -> W)
    freq_key = freq.split("-")[0] if freq else "D"
    seasonal_periods = seasonal_map.get(freq_key, 1)

    history = [
        {"date": idx.isoformat(), "value": float(val)}
        for idx, val in df["value"].items()
    ]

    use_seasonal = seasonal_periods > 1 and len(df) >= 2 * seasonal_periods
    confidence = "high" if use_seasonal else "low"
    method = "ets_holt_winters" if use_seasonal else "linear_trend"

    try:
        if use_seasonal:
            model = ExponentialSmoothing(
                df["value"].astype(float),
                trend="add",
                seasonal="add",
                seasonal_periods=seasonal_periods,
                initialization_method="estimated",
            )
            fitted = model.fit(optimized=True)
            fc = fitted.forecast(horizon)
            # Approximate CI using residual std
            resid_std = float(np.nanstd(fitted.resid)) if fitted.resid is not None else 0.0
            forecasts = []
            for i, (idx, val) in enumerate(fc.items(), start=1):
                forecasts.append(
                    {
                        "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                        "value": float(val),
                        "lower": float(val - 1.96 * resid_std * np.sqrt(i)),
                        "upper": float(val + 1.96 * resid_std * np.sqrt(i)),
                    }
                )
        else:
            # Linear trend fallback on integer positions
            y = df["value"].astype(float).to_numpy()
            x = np.arange(len(y), dtype=float)
            coef = np.polyfit(x, y, 1)
            poly = np.poly1d(coef)
            resid_std = float(np.std(y - poly(x)))
            last_idx = df.index[-1]
            # Estimate step from median delta
            step = df.index.to_series().diff().median()
            if pd.isna(step):
                step = pd.Timedelta(days=1)
            forecasts = []
            for i in range(1, horizon + 1):
                future_date = last_idx + (step * i)
                val = float(poly(len(y) - 1 + i))
                forecasts.append(
                    {
                        "date": future_date.isoformat()
                        if hasattr(future_date, "isoformat")
                        else str(future_date),
                        "value": val,
                        "lower": val - 1.96 * resid_std * np.sqrt(i),
                        "upper": val + 1.96 * resid_std * np.sqrt(i),
                    }
                )
    except Exception as exc:
        return {
            "error": "forecast_failed",
            "reason": str(exc),
            "frequency": freq,
            "confidence": "low",
        }

    return {
        "history": history,
        "forecast": forecasts,
        "frequency": freq,
        "frequency_inferred": inferred,
        "seasonal_periods": seasonal_periods,
        "confidence": confidence,
        "method": method,
        "horizon": horizon,
        "note": (
            "Full seasonal ETS fit"
            if confidence == "high"
            else "Low-confidence linear-trend fallback (insufficient seasonal history)"
        ),
    }
