"""
Plot Generators
================
Individual Plotly chart generators for the dashboard and reports.
Each function returns a plotly Figure object.

All time-series plots resample to hourly averages for clean rendering
at the 168-hour / 672-step scale.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


_PALETTE = {
    "baseline":  "#636EFA",
    "optimized": "#00CC96",
    "warning":   "#FFA15A",
    "danger":    "#EF553B",
    "neutral":   "#AB63FA",
    "bg":        "#0f1117",
    "surface":   "#1a1d2e",
    "grid":      "rgba(255,255,255,0.07)",
    "text":      "#e8eaf6",
    "subtext":   "#90caf9",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dark_layout(fig: go.Figure, title: str = "", height: int = 400) -> go.Figure:
    """Apply consistent dark theme."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=_PALETTE["subtext"]), x=0.02),
        paper_bgcolor=_PALETTE["bg"],
        plot_bgcolor=_PALETTE["surface"],
        font=dict(color=_PALETTE["text"], family="Inter, system-ui, sans-serif", size=12),
        height=height,
        margin=dict(l=60, r=20, t=55, b=50),
        legend=dict(
            bgcolor="rgba(255,255,255,0.04)",
            bordercolor="rgba(255,255,255,0.12)",
            borderwidth=1,
            font=dict(size=11),
        ),
        xaxis=dict(gridcolor=_PALETTE["grid"], zerolinecolor=_PALETTE["grid"]),
        yaxis=dict(gridcolor=_PALETTE["grid"], zerolinecolor=_PALETTE["grid"]),
        hovermode="x unified",
    )
    return fig


def _resample_hourly(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Resample a 15-min dataframe to 1-h mean for cleaner charts."""
    if df.empty:
        return df
    ts = pd.to_datetime(df["timestamp"])
    value_cols = [c for c in cols if c != "timestamp"]
    out = df[value_cols].copy()
    out.index = ts
    resampled = out.resample("1h").mean()
    resampled.insert(0, "timestamp", resampled.index)
    resampled = resampled.reset_index(drop=True)
    return resampled


def _add_day_night_bands(fig: go.Figure, ts: pd.Series, row: int = 1, col: int = 1) -> None:
    """Add alternating shaded day/night bands on a time-series chart."""
    if ts.empty:
        return
    start = ts.iloc[0].normalize()
    end   = ts.iloc[-1]
    day = start
    while day <= end:
        # Night: 0-8 h  →  dark band
        night_end = day + pd.Timedelta(hours=8)
        fig.add_vrect(
            x0=str(day), x1=str(min(night_end, end + pd.Timedelta(hours=1))),
            fillcolor="rgba(0,0,0,0.18)", layer="below", line_width=0,
            row=row, col=col,
        )
        day += pd.Timedelta(hours=24)


# ── Chart functions ───────────────────────────────────────────────────────────

def plot_energy_comparison(
    baseline_df: pd.DataFrame,
    optimized_df: pd.DataFrame,
) -> go.Figure:
    """Cumulative energy with a shaded savings area between the two runs."""
    fig = go.Figure()

    b = _resample_hourly(baseline_df, ["timestamp", "total_electricity_kwh"]) if not baseline_df.empty else pd.DataFrame()
    o = _resample_hourly(optimized_df, ["timestamp", "total_electricity_kwh"]) if not optimized_df.empty else pd.DataFrame()

    if not b.empty:
        b_cum = b["total_electricity_kwh"].cumsum()
        fig.add_trace(go.Scatter(
            x=b["timestamp"], y=b_cum,
            name="Baseline",
            line=dict(color=_PALETTE["baseline"], width=2, dash="dot"),
            hovertemplate="%{y:.1f} kWh<extra>Baseline</extra>",
        ))

    if not o.empty:
        o_cum = o["total_electricity_kwh"].cumsum()
        fig.add_trace(go.Scatter(
            x=o["timestamp"], y=o_cum,
            name="Optimized",
            line=dict(color=_PALETTE["optimized"], width=2.5),
            fill="tonexty" if not b.empty else "tozeroy",
            fillcolor="rgba(0,204,150,0.08)",
            hovertemplate="%{y:.1f} kWh<extra>Optimized</extra>",
        ))

    _dark_layout(fig, "Cumulative Energy Consumption (kWh)", 380)
    fig.update_layout(yaxis_title="kWh", xaxis_title="Date")
    return fig


def plot_temperature_comparison(
    baseline_df: pd.DataFrame,
    optimized_df: pd.DataFrame,
    comfort_min: float = 21.0,
    comfort_max: float = 25.0,
) -> go.Figure:
    """Indoor temperature with ASHRAE comfort band and day/night shading."""
    fig = go.Figure()

    b = _resample_hourly(baseline_df, ["timestamp", "indoor_temp_c"]) if not baseline_df.empty else pd.DataFrame()
    o = _resample_hourly(optimized_df, ["timestamp", "indoor_temp_c", "cooling_setpoint_c", "heating_setpoint_c"]) if not optimized_df.empty else pd.DataFrame()

    ts_ref = b["timestamp"] if not b.empty else (o["timestamp"] if not o.empty else pd.Series(dtype="datetime64[ns]"))
    if not ts_ref.empty:
        _add_day_night_bands(fig, ts_ref)
        # Comfort zone fill
        fig.add_trace(go.Scatter(
            x=list(ts_ref) + list(ts_ref[::-1]),
            y=[comfort_max] * len(ts_ref) + [comfort_min] * len(ts_ref),
            fill="toself", fillcolor="rgba(0,204,150,0.06)",
            line=dict(color="rgba(0,0,0,0)"),
            name=f"Comfort {comfort_min}-{comfort_max}°C",
            hoverinfo="skip",
        ))

    if not b.empty:
        fig.add_trace(go.Scatter(
            x=b["timestamp"], y=b["indoor_temp_c"],
            name="Baseline Temp", mode="lines",
            line=dict(color=_PALETTE["baseline"], width=1.5, dash="dot"),
            hovertemplate="%{y:.1f}°C<extra>Baseline</extra>",
        ))

    if not o.empty:
        fig.add_trace(go.Scatter(
            x=o["timestamp"], y=o["indoor_temp_c"],
            name="Optimized Temp", mode="lines",
            line=dict(color=_PALETTE["optimized"], width=2),
            hovertemplate="%{y:.1f}°C<extra>Optimized</extra>",
        ))
        if "cooling_setpoint_c" in o.columns:
            fig.add_trace(go.Scatter(
                x=o["timestamp"], y=o["cooling_setpoint_c"],
                name="Cool Setpoint", mode="lines",
                line=dict(color=_PALETTE["danger"], width=1, dash="dash"),
                hovertemplate="%{y:.1f}°C<extra>Cool SP</extra>",
            ))
        if "heating_setpoint_c" in o.columns:
            fig.add_trace(go.Scatter(
                x=o["timestamp"], y=o["heating_setpoint_c"],
                name="Heat Setpoint", mode="lines",
                line=dict(color=_PALETTE["warning"], width=1, dash="dash"),
                hovertemplate="%{y:.1f}°C<extra>Heat SP</extra>",
            ))

    _dark_layout(fig, "Indoor Temperature (°C) with HVAC Setpoints", 400)
    fig.update_layout(yaxis_title="Temperature (°C)", xaxis_title="Date")
    return fig


def plot_pmv_timeline(
    df: pd.DataFrame,
    mode: str = "optimized",
    baseline_df: Optional[pd.DataFrame] = None,
) -> go.Figure:
    """PMV comfort index — both modes if available."""
    fig = go.Figure()

    # Limit bands
    fig.add_hrect(y0=0.5, y1=3, fillcolor="rgba(239,85,59,0.06)", line_width=0, name="Too Warm")
    fig.add_hrect(y0=-3, y1=-0.5, fillcolor="rgba(99,110,250,0.06)", line_width=0, name="Too Cool")
    fig.add_hline(y=0.5, line_dash="dash", line_color=_PALETTE["warning"], line_width=1,
                  annotation_text="+0.5 (warm limit)", annotation_position="top right")
    fig.add_hline(y=-0.5, line_dash="dash", line_color=_PALETTE["neutral"], line_width=1,
                  annotation_text="-0.5 (cool limit)", annotation_position="bottom right")
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)", line_width=1)

    if baseline_df is not None and not baseline_df.empty:
        b = _resample_hourly(baseline_df, ["timestamp", "pmv"])
        fig.add_trace(go.Scatter(
            x=b["timestamp"], y=b["pmv"],
            name="Baseline PMV",
            line=dict(color=_PALETTE["baseline"], width=1.5, dash="dot"),
            hovertemplate="%{y:.2f}<extra>Baseline PMV</extra>",
        ))

    if not df.empty:
        o = _resample_hourly(df, ["timestamp", "pmv"])
        fig.add_trace(go.Scatter(
            x=o["timestamp"], y=o["pmv"],
            name="Optimized PMV",
            line=dict(color=_PALETTE["optimized"], width=2),
            fill="tozeroy", fillcolor="rgba(0,204,150,0.06)",
            hovertemplate="%{y:.2f}<extra>Optimized PMV</extra>",
        ))

    _dark_layout(fig, "PMV Comfort Index (ASHRAE-55: -0.5 to +0.5)", 380)
    fig.update_layout(yaxis_title="PMV", xaxis_title="Date", yaxis_range=[-3, 3])
    return fig


def plot_hvac_power(
    baseline_df: pd.DataFrame,
    optimized_df: pd.DataFrame,
) -> go.Figure:
    """HVAC power comparison — area chart, hourly resampled."""
    fig = go.Figure()

    b = _resample_hourly(baseline_df, ["timestamp", "hvac_power_kw"]) if not baseline_df.empty else pd.DataFrame()
    o = _resample_hourly(optimized_df, ["timestamp", "hvac_power_kw"]) if not optimized_df.empty else pd.DataFrame()

    ts_ref = b["timestamp"] if not b.empty else (o["timestamp"] if not o.empty else pd.Series(dtype="datetime64[ns]"))
    if not ts_ref.empty:
        _add_day_night_bands(fig, ts_ref)

    if not b.empty:
        fig.add_trace(go.Scatter(
            x=b["timestamp"], y=b["hvac_power_kw"],
            name="Baseline HVAC",
            line=dict(color=_PALETTE["baseline"], width=1.5, dash="dot"),
            hovertemplate="%{y:.2f} kW<extra>Baseline</extra>",
        ))

    if not o.empty:
        fig.add_trace(go.Scatter(
            x=o["timestamp"], y=o["hvac_power_kw"],
            name="Optimized HVAC",
            line=dict(color=_PALETTE["optimized"], width=2),
            fill="tozeroy", fillcolor="rgba(0,204,150,0.08)",
            hovertemplate="%{y:.2f} kW<extra>Optimized</extra>",
        ))

    _dark_layout(fig, "HVAC Power Draw (kW)", 360)
    fig.update_layout(yaxis_title="Power (kW)", xaxis_title="Date")
    return fig


def plot_occupancy(df: pd.DataFrame) -> go.Figure:
    """Occupancy profile — line chart, hourly resampled."""
    fig = go.Figure()

    if not df.empty:
        o = _resample_hourly(df, ["timestamp", "occupancy_fraction"])
        pct = (o["occupancy_fraction"] * 100).round(1)
        ts_ref = o["timestamp"]
        _add_day_night_bands(fig, ts_ref)

        fig.add_trace(go.Scatter(
            x=ts_ref, y=pct,
            name="Occupancy",
            mode="lines",
            line=dict(color=_PALETTE["neutral"], width=2),
            fill="tozeroy", fillcolor="rgba(171,99,250,0.15)",
            hovertemplate="%{y:.0f}%<extra>Occupancy</extra>",
        ))

    _dark_layout(fig, "Building Occupancy Profile (%)", 320)
    fig.update_layout(yaxis_title="Occupancy (%)", xaxis_title="Date", yaxis_range=[0, 110])
    return fig


def plot_carbon_emissions(
    baseline_df: pd.DataFrame,
    optimized_df: pd.DataFrame,
) -> go.Figure:
    """Cumulative carbon emissions with savings fill."""
    fig = go.Figure()

    b = _resample_hourly(baseline_df, ["timestamp", "carbon_kg_co2"]) if not baseline_df.empty else pd.DataFrame()
    o = _resample_hourly(optimized_df, ["timestamp", "carbon_kg_co2"]) if not optimized_df.empty else pd.DataFrame()

    if not b.empty:
        b_cum = b["carbon_kg_co2"].cumsum()
        fig.add_trace(go.Scatter(
            x=b["timestamp"], y=b_cum,
            name="Baseline CO2",
            line=dict(color=_PALETTE["danger"], width=2, dash="dot"),
            hovertemplate="%{y:.1f} kg<extra>Baseline CO2</extra>",
        ))

    if not o.empty:
        o_cum = o["carbon_kg_co2"].cumsum()
        fig.add_trace(go.Scatter(
            x=o["timestamp"], y=o_cum,
            name="Optimized CO2",
            line=dict(color=_PALETTE["optimized"], width=2.5),
            fill="tonexty" if not b.empty else "tozeroy",
            fillcolor="rgba(0,204,150,0.08)",
            hovertemplate="%{y:.1f} kg<extra>Optimized CO2</extra>",
        ))

    _dark_layout(fig, "Cumulative Carbon Emissions (kg CO2)", 380)
    fig.update_layout(yaxis_title="kg CO2", xaxis_title="Date")
    return fig


def plot_energy_breakdown(df: pd.DataFrame, mode: str = "optimized") -> go.Figure:
    """Stacked area chart of HVAC / lighting / equipment — hourly resampled."""
    fig = go.Figure()
    if df.empty:
        return fig

    cols = ["timestamp", "hvac_electricity_kwh", "lighting_electricity_kwh", "equipment_electricity_kwh"]
    h = _resample_hourly(df, cols)

    fig.add_trace(go.Scatter(
        x=h["timestamp"], y=h["hvac_electricity_kwh"],
        stackgroup="one", name="HVAC",
        line=dict(width=0), fillcolor="rgba(99,110,250,0.75)",
        hovertemplate="%{y:.3f} kWh<extra>HVAC</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=h["timestamp"], y=h["lighting_electricity_kwh"],
        stackgroup="one", name="Lighting",
        line=dict(width=0), fillcolor="rgba(0,204,150,0.75)",
        hovertemplate="%{y:.3f} kWh<extra>Lighting</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=h["timestamp"], y=h["equipment_electricity_kwh"],
        stackgroup="one", name="Equipment",
        line=dict(width=0), fillcolor="rgba(171,99,250,0.75)",
        hovertemplate="%{y:.3f} kWh<extra>Equipment</extra>",
    ))

    _dark_layout(fig, f"Energy Breakdown by Category -- {mode.title()}", 360)
    fig.update_layout(yaxis_title="kWh / hour", xaxis_title="Date")
    return fig


def plot_comfort_violations(violations_df: pd.DataFrame) -> go.Figure:
    """Bar chart of comfort violation counts by type."""
    fig = go.Figure()
    if violations_df.empty:
        fig.add_annotation(
            text="No comfort violations recorded",
            showarrow=False,
            font=dict(size=16, color=_PALETTE["optimized"]),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        _dark_layout(fig, "Comfort Violations", 300)
        return fig

    counts = violations_df["violation_type"].value_counts()
    colors = [_PALETTE["danger"] if "high" in t else _PALETTE["warning"] for t in counts.index]
    fig.add_trace(go.Bar(
        x=counts.index.tolist(),
        y=counts.values.tolist(),
        marker_color=colors,
        name="Violations",
        hovertemplate="%{x}: %{y}<extra></extra>",
    ))

    _dark_layout(fig, "Comfort Violations by Type", 360)
    fig.update_layout(yaxis_title="Count", xaxis_title="Violation Type")
    return fig


def plot_savings_summary(comparison: dict) -> go.Figure:
    """KPI gauge + big-number indicators for savings metrics."""
    savings_pct   = comparison.get("savings_pct", 0)
    cost_savings  = comparison.get("cost_savings", 0)
    carbon_savings = comparison.get("carbon_savings_kg", 0)

    fig = make_subplots(
        rows=1, cols=3,
        specs=[[{"type": "indicator"}, {"type": "indicator"}, {"type": "indicator"}]],
    )

    fig.add_trace(go.Indicator(
        mode="gauge+number",
        value=savings_pct,
        title={"text": "Energy Savings (%)", "font": {"size": 13}},
        gauge={
            "axis": {"range": [0, 40], "tickcolor": _PALETTE["subtext"]},
            "bar": {"color": _PALETTE["optimized"]},
            "bgcolor": _PALETTE["surface"],
            "steps": [
                {"range": [0, 10],  "color": "rgba(0,204,150,0.1)"},
                {"range": [10, 25], "color": "rgba(0,204,150,0.2)"},
                {"range": [25, 40], "color": "rgba(0,204,150,0.3)"},
            ],
        },
        number={"suffix": "%", "font": {"color": _PALETTE["optimized"], "size": 28}},
    ), row=1, col=1)

    fig.add_trace(go.Indicator(
        mode="number",
        value=cost_savings,
        title={"text": "Cost Savings ($)", "font": {"size": 13}},
        number={"prefix": "$", "font": {"color": _PALETTE["optimized"], "size": 36}},
    ), row=1, col=2)

    fig.add_trace(go.Indicator(
        mode="number",
        value=carbon_savings,
        title={"text": "Carbon Savings (kg CO2)", "font": {"size": 13}},
        number={"suffix": " kg", "font": {"color": _PALETTE["optimized"], "size": 36}},
    ), row=1, col=3)

    _dark_layout(fig, "Optimization Results", 260)
    return fig
