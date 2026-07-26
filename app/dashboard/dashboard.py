"""
Premium Dashboard Generator - Eco-Loop Building Agents
Generates a tabbed, animated HTML dashboard.
Charts are serialised as Plotly JSON and rendered client-side.
"""

from __future__ import annotations

import webbrowser

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from loguru import logger
from plotly.subplots import make_subplots

from app.config import get_config
from app.database.repository import (
    compare_simulations,
    get_metrics_dataframe,
    get_recent_decisions,
    get_violations_dataframe,
    list_simulation_runs,
)

P = {
    "bg": "#080c14",
    "surface": "#0f1623",
    "card": "#141a28",
    "border": "rgba(255,255,255,0.07)",
    "accent1": "#38bdf8",
    "accent2": "#34d399",
    "accent3": "#f472b6",
    "base": "#818cf8",
    "opt": "#34d399",
    "warn": "#fb923c",
    "danger": "#f87171",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
    "grid": "rgba(255,255,255,0.06)",
}


def _resample(df, cols, rule="1h"):
    if df.empty:
        return df
    ts = pd.to_datetime(df["timestamp"])
    sub = df[cols].copy()
    sub.index = ts
    r = sub.resample(rule).mean()
    r.insert(0, "timestamp", r.index)
    return r.reset_index(drop=True)


def _dark(fig, title="", h=380):
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color=P["muted"]), x=0.02, y=0.97),
        paper_bgcolor=P["surface"],
        plot_bgcolor=P["card"],
        font=dict(color=P["text"], family="Inter, system-ui, sans-serif", size=11),
        height=h,
        margin=dict(l=55, r=16, t=48, b=44),
        legend=dict(
            bgcolor="rgba(255,255,255,0.04)",
            bordercolor=P["border"],
            borderwidth=1,
            font=dict(size=10),
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="right",
            x=1,
        ),
        hovermode="x unified",
        xaxis=dict(
            gridcolor=P["grid"],
            zerolinecolor=P["grid"],
            showspikes=True,
            spikecolor=P["muted"],
            spikethickness=1,
        ),
        yaxis=dict(gridcolor=P["grid"], zerolinecolor=P["grid"]),
    )
    return fig


def _night_bands(fig, ts):
    if ts.empty:
        return
    day = pd.to_datetime(ts.iloc[0]).normalize()
    end = pd.to_datetime(ts.iloc[-1])
    while day <= end:
        fig.add_vrect(
            x0=str(day),
            x1=str(min(day + pd.Timedelta(hours=8), end + pd.Timedelta(hours=1))),
            fillcolor="rgba(0,0,0,0.22)",
            layer="below",
            line_width=0,
        )
        day += pd.Timedelta(hours=24)


def _j(fig):
    return pio.to_json(fig, validate=False)


def _c_savings(cmp):
    pct = cmp.get("savings_pct", 0)
    kwh = cmp.get("savings_kwh", 0)
    fig = make_subplots(
        rows=1,
        cols=2,
        specs=[[{"type": "indicator"}, {"type": "indicator"}]],
        column_widths=[0.55, 0.45],
    )
    fig.add_trace(
        go.Indicator(
            mode="gauge+number",
            value=pct,
            title={"text": "Energy Savings", "font": {"size": 13, "color": P["muted"]}},
            gauge={
                "axis": {"range": [0, 30], "tickcolor": P["muted"], "tickfont": {"size": 10}},
                "bar": {"color": P["opt"], "thickness": 0.25},
                "bgcolor": P["card"],
                "bordercolor": P["border"],
                "steps": [
                    {"range": [0, 10], "color": "rgba(52,211,153,0.08)"},
                    {"range": [10, 20], "color": "rgba(52,211,153,0.16)"},
                    {"range": [20, 30], "color": "rgba(52,211,153,0.24)"},
                ],
                "threshold": {"line": {"color": P["accent1"], "width": 2}, "value": pct},
            },
            number={"suffix": "%", "font": {"size": 32, "color": P["opt"]}},
            domain={"row": 0, "column": 0},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=kwh,
            title={"text": "kWh Saved", "font": {"size": 13, "color": P["muted"]}},
            number={"suffix": " kWh", "font": {"size": 26, "color": P["accent1"]}},
            domain={"row": 0, "column": 1},
        ),
        row=1,
        col=2,
    )
    _dark(fig, "", 280)
    return _j(fig)


def _c_hourly(b_df, o_df):
    fig = go.Figure()
    for df, name, color, dash in [
        (b_df, "Baseline", P["base"], "dot"),
        (o_df, "Optimised", P["opt"], "solid"),
    ]:
        if df.empty:
            continue
        d2 = df.copy()
        d2["hour"] = pd.to_datetime(d2["timestamp"]).dt.hour
        prof = d2.groupby("hour")["total_electricity_kwh"].mean()
        fig.add_trace(
            go.Scatter(
                x=list(prof.index),
                y=list(prof.values),
                name=name,
                mode="lines+markers",
                line=dict(color=color, width=2, dash=dash),
                marker=dict(size=5),
                fill="tozeroy" if name == "Optimised" else "none",
                fillcolor="rgba(52,211,153,0.07)",
            )
        )
    _dark(fig, "Average Energy by Hour-of-Day (kWh/timestep)", 340)
    fig.update_layout(
        xaxis=dict(
            title="Hour of Day",
            tickvals=list(range(0, 24, 3)),
            ticktext=[f"{h:02d}:00" for h in range(0, 24, 3)],
        ),
        yaxis_title="kWh / timestep",
    )
    return _j(fig)


def _c_bars(cmp):
    base = cmp.get("baseline", {})
    opt = cmp.get("optimized", cmp.get("optimised", {}))

    def _mini(title, b_val, o_val, suffix=""):
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                y=["Baseline", "Optimised"],
                x=[b_val, o_val],
                orientation="h",
                marker_color=[P["base"], P["opt"]],
                text=[f"{b_val}{suffix}", f"{o_val}{suffix}"],
                textposition="auto",
                opacity=0.85,
            )
        )
        _dark(fig, title, 160)
        fig.update_layout(
            margin=dict(l=70, r=10, t=30, b=10),
            xaxis=dict(visible=False),
            yaxis=dict(autorange="reversed"),
        )
        return _j(fig)

    return {
        "c_bar_energy": _mini(
            "Total Energy (kWh)",
            round(base.get("total_energy_kwh", 0), 1),
            round(opt.get("total_energy_kwh", 0), 1),
        ),
        "c_bar_cost": _mini(
            "Total Cost ($)",
            round(base.get("total_cost", 0), 2),
            round(opt.get("total_cost", 0), 2),
        ),
        "c_bar_carbon": _mini(
            "Carbon Footprint (kg CO2)",
            round(base.get("total_carbon_kg", 0), 1),
            round(opt.get("total_carbon_kg", 0), 1),
        ),
        "c_bar_viol": _mini(
            "Comfort Violations",
            base.get("comfort_violations", 0),
            opt.get("comfort_violations", 0),
        ),
    }


def _c_energy(b_df, o_df):
    b = _resample(b_df, ["total_electricity_kwh"]) if not b_df.empty else pd.DataFrame()
    o = _resample(o_df, ["total_electricity_kwh"]) if not o_df.empty else pd.DataFrame()
    fig = go.Figure()
    if not b.empty:
        fig.add_trace(
            go.Scatter(
                x=list(b["timestamp"]),
                y=list(b["total_electricity_kwh"].cumsum()),
                name="Baseline",
                line=dict(color=P["base"], width=2, dash="dot"),
            )
        )
    if not o.empty:
        fig.add_trace(
            go.Scatter(
                x=list(o["timestamp"]),
                y=list(o["total_electricity_kwh"].cumsum()),
                name="Optimised",
                line=dict(color=P["opt"], width=2.5),
                fill="tonexty" if not b.empty else "tozeroy",
                fillcolor="rgba(52,211,153,0.07)",
            )
        )
    _dark(fig, "Cumulative Energy Consumption (kWh)", 380)
    fig.update_layout(yaxis_title="kWh", xaxis_title="Date")
    return _j(fig)


def _c_carbon(b_df, o_df):
    b = _resample(b_df, ["carbon_kg_co2"]) if not b_df.empty else pd.DataFrame()
    o = _resample(o_df, ["carbon_kg_co2"]) if not o_df.empty else pd.DataFrame()
    fig = go.Figure()
    if not b.empty:
        fig.add_trace(
            go.Scatter(
                x=list(b["timestamp"]),
                y=list(b["carbon_kg_co2"].cumsum()),
                name="Baseline CO2",
                line=dict(color=P["danger"], width=2, dash="dot"),
            )
        )
    if not o.empty:
        fig.add_trace(
            go.Scatter(
                x=list(o["timestamp"]),
                y=list(o["carbon_kg_co2"].cumsum()),
                name="Optimised CO2",
                line=dict(color=P["opt"], width=2.5),
                fill="tonexty" if not b.empty else "tozeroy",
                fillcolor="rgba(52,211,153,0.06)",
            )
        )
    _dark(fig, "Cumulative Carbon Emissions (kg CO2)", 380)
    fig.update_layout(yaxis_title="kg CO2", xaxis_title="Date")
    return _j(fig)


def _c_breakdown(o_df):
    cols = ["hvac_electricity_kwh", "lighting_electricity_kwh", "equipment_electricity_kwh"]
    h = _resample(o_df, cols) if not o_df.empty else pd.DataFrame()
    fig = go.Figure()
    if not h.empty:
        for col, name, color in [
            ("hvac_electricity_kwh", "HVAC", "rgba(129,140,248,0.8)"),
            ("lighting_electricity_kwh", "Lighting", "rgba(52,211,153,0.8)"),
            ("equipment_electricity_kwh", "Equipment", "rgba(244,114,182,0.8)"),
        ]:
            fig.add_trace(
                go.Scatter(
                    x=list(h["timestamp"]),
                    y=list(h[col]),
                    stackgroup="one",
                    name=name,
                    line=dict(width=0),
                    fillcolor=color,
                )
            )
    _dark(fig, "Optimised - Energy Breakdown by Category (kWh/hr)", 360)
    fig.update_layout(yaxis_title="kWh/hour", xaxis_title="Date")
    return _j(fig)


def _c_temp(b_df, o_df, tmin=21.0, tmax=25.0):
    b = _resample(b_df, ["indoor_temp_c", "outdoor_temp_c"]) if not b_df.empty else pd.DataFrame()
    o = (
        _resample(
            o_df, ["indoor_temp_c", "cooling_setpoint_c", "heating_setpoint_c", "outdoor_temp_c"]
        )
        if not o_df.empty
        else pd.DataFrame()
    )
    fig = go.Figure()
    ts = (
        o["timestamp"]
        if not o.empty
        else (b["timestamp"] if not b.empty else pd.Series(dtype="datetime64[ns]"))
    )
    if not ts.empty:
        _night_bands(fig, ts)
        fig.add_trace(
            go.Scatter(
                x=list(ts) + list(ts[::-1]),
                y=[tmax] * len(ts) + [tmin] * len(ts),
                fill="toself",
                fillcolor="rgba(52,211,153,0.05)",
                line=dict(color="rgba(0,0,0,0)"),
                name=f"Comfort {tmin}-{tmax}C",
                hoverinfo="skip",
            )
        )
    if not o.empty:
        fig.add_trace(
            go.Scatter(
                x=list(o["timestamp"]),
                y=list(o["outdoor_temp_c"]),
                name="Outdoor",
                line=dict(color=P["muted"], width=1, dash="dot"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=list(o["timestamp"]),
                y=list(o["heating_setpoint_c"]),
                name="Heat SP",
                line=dict(color=P["warn"], width=1.2, dash="dash"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=list(o["timestamp"]),
                y=list(o["cooling_setpoint_c"]),
                name="Cool SP",
                line=dict(color=P["danger"], width=1.2, dash="dash"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=list(o["timestamp"]),
                y=list(o["indoor_temp_c"]),
                name="Indoor (Opt)",
                line=dict(color=P["opt"], width=2.5),
            )
        )
    if not b.empty:
        fig.add_trace(
            go.Scatter(
                x=list(b["timestamp"]),
                y=list(b["indoor_temp_c"]),
                name="Indoor (Base)",
                line=dict(color=P["base"], width=1.5, dash="dot"),
            )
        )
    _dark(fig, "Indoor Temperature - Baseline vs Optimised with HVAC Setpoints", 420)
    fig.update_layout(yaxis_title="Temperature (C)", xaxis_title="Date")
    return _j(fig)


def _c_pmv(b_df, o_df):
    b = _resample(b_df, ["pmv"]) if not b_df.empty else pd.DataFrame()
    o = _resample(o_df, ["pmv"]) if not o_df.empty else pd.DataFrame()
    fig = go.Figure()
    fig.add_hrect(y0=0.5, y1=3, fillcolor="rgba(248,113,113,0.06)", line_width=0)
    fig.add_hrect(y0=-3, y1=-0.5, fillcolor="rgba(129,140,248,0.06)", line_width=0)
    fig.add_hline(
        y=0.5,
        line_dash="dash",
        line_color=P["warn"],
        line_width=1,
        annotation_text="+0.5 warm limit",
        annotation_font_size=10,
    )
    fig.add_hline(
        y=-0.5,
        line_dash="dash",
        line_color=P["accent1"],
        line_width=1,
        annotation_text="-0.5 cool limit",
        annotation_font_size=10,
    )
    fig.add_hline(y=0, line_dash="dot", line_color=P["grid"], line_width=1)
    if not b.empty:
        fig.add_trace(
            go.Scatter(
                x=list(b["timestamp"]),
                y=list(b["pmv"]),
                name="Baseline PMV",
                line=dict(color=P["base"], width=1.5, dash="dot"),
            )
        )
    if not o.empty:
        fig.add_trace(
            go.Scatter(
                x=list(o["timestamp"]),
                y=list(o["pmv"]),
                name="Optimised PMV",
                line=dict(color=P["opt"], width=2.5),
                fill="tozeroy",
                fillcolor="rgba(52,211,153,0.05)",
            )
        )
    _dark(fig, "PMV Comfort Index - ASHRAE-55 (acceptable: -0.5 to +0.5)", 380)
    fig.update_layout(yaxis_title="PMV", xaxis_title="Date", yaxis_range=[-3, 3])
    return _j(fig)


def _c_hvac(b_df, o_df):
    b = _resample(b_df, ["hvac_power_kw"]) if not b_df.empty else pd.DataFrame()
    o = _resample(o_df, ["hvac_power_kw"]) if not o_df.empty else pd.DataFrame()
    fig = go.Figure()
    ts = (
        o["timestamp"]
        if not o.empty
        else (b["timestamp"] if not b.empty else pd.Series(dtype="datetime64[ns]"))
    )
    if not ts.empty:
        _night_bands(fig, ts)
    if not b.empty:
        fig.add_trace(
            go.Scatter(
                x=list(b["timestamp"]),
                y=list(b["hvac_power_kw"]),
                name="Baseline",
                line=dict(color=P["base"], width=1.5, dash="dot"),
            )
        )
    if not o.empty:
        fig.add_trace(
            go.Scatter(
                x=list(o["timestamp"]),
                y=list(o["hvac_power_kw"]),
                name="Optimised",
                line=dict(color=P["opt"], width=2.5),
                fill="tozeroy",
                fillcolor="rgba(52,211,153,0.07)",
            )
        )
    _dark(fig, "HVAC Power Draw - Baseline vs Optimised (kW)", 360)
    fig.update_layout(yaxis_title="Power (kW)", xaxis_title="Date")
    return _j(fig)


def _c_occ(o_df):
    h = _resample(o_df, ["occupancy_fraction", "co2_ppm"]) if not o_df.empty else pd.DataFrame()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    ts = h["timestamp"] if not h.empty else pd.Series(dtype="datetime64[ns]")
    if not ts.empty:
        _night_bands(fig, ts)
    if not h.empty:
        fig.add_trace(
            go.Scatter(
                x=list(h["timestamp"]),
                y=list((h["occupancy_fraction"] * 100).round(1)),
                name="Occupancy (%)",
                line=dict(color=P["accent3"], width=2),
                fill="tozeroy",
                fillcolor="rgba(244,114,182,0.08)",
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=list(h["timestamp"]),
                y=list(h["co2_ppm"]),
                name="CO2 (ppm)",
                line=dict(color=P["warn"], width=1.5),
            ),
            secondary_y=True,
        )
    _dark(fig, "Building Occupancy (%) and CO2 Levels (ppm)", 360)
    fig.update_yaxes(title_text="Occupancy (%)", secondary_y=False, range=[0, 110])
    fig.update_yaxes(title_text="CO2 (ppm)", secondary_y=True, rangemode="tozero")
    fig.update_layout(xaxis_title="Date")
    return _j(fig)


def _c_viol(v_df):
    fig = go.Figure()
    if v_df.empty:
        fig.add_annotation(
            text="No comfort violations recorded",
            showarrow=False,
            font=dict(size=16, color=P["opt"]),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
        )
    else:
        counts = v_df["violation_type"].value_counts()
        colors = [P["danger"] if "high" in t else P["warn"] for t in counts.index]
        fig.add_trace(
            go.Bar(x=counts.index.tolist(), y=counts.values.tolist(), marker_color=colors)
        )
    _dark(fig, "Comfort Violations by Type", 320)
    fig.update_layout(yaxis_title="Count", xaxis_title="Violation Type", showlegend=False)
    return _j(fig)


def _cmp_rows(cmp):
    base = cmp.get("baseline", {})
    opt = cmp.get("optimized", cmp.get("optimised", {}))

    def row(label, bv, ov, delta, lib=True):
        if isinstance(delta, float):
            s = "-" if delta < 0 else "+"
            cls = "val-pos" if (delta < 0) == lib else "val-neg"
            d = f'<span class="{cls}">{s}{abs(delta):.2f}</span>'
        else:
            d = str(delta)
        return f"<tr><td>{label}</td><td class='val-base'>{bv}</td><td class='val-opt'>{ov}</td><td>{d}</td></tr>"

    rows = [
        row(
            "Total Energy (kWh)",
            f"{base.get('total_energy_kwh', 0):.2f}",
            f"{opt.get('total_energy_kwh', 0):.2f}",
            opt.get("total_energy_kwh", 0) - base.get("total_energy_kwh", 0),
        ),
        row(
            "Total Cost ($)",
            f"${base.get('total_cost', 0):.2f}",
            f"${opt.get('total_cost', 0):.2f}",
            opt.get("total_cost", 0) - base.get("total_cost", 0),
        ),
        row(
            "Carbon (kg CO2)",
            f"{base.get('total_carbon_kg', 0):.2f}",
            f"{opt.get('total_carbon_kg', 0):.2f}",
            opt.get("total_carbon_kg", 0) - base.get("total_carbon_kg", 0),
        ),
        row(
            "Avg PMV",
            f"{base.get('avg_pmv', 0):.3f}",
            f"{opt.get('avg_pmv', 0):.3f}",
            opt.get("avg_pmv", 0) - base.get("avg_pmv", 0),
        ),
        row(
            "Comfort Violations",
            str(base.get("comfort_violations", 0)),
            str(opt.get("comfort_violations", 0)),
            opt.get("comfort_violations", 0) - base.get("comfort_violations", 0),
        ),
        row(
            "Avg Temp (C)",
            f"{base.get('avg_temp_c', 0):.2f}",
            f"{opt.get('avg_temp_c', 0):.2f}",
            opt.get("avg_temp_c", 0) - base.get("avg_temp_c", 0),
            lib=False,
        ),
        row(
            "Peak HVAC (kW)",
            f"{base.get('peak_hvac_kw', 0):.2f}",
            f"{opt.get('peak_hvac_kw', 0):.2f}",
            opt.get("peak_hvac_kw", 0) - base.get("peak_hvac_kw", 0),
        ),
        row(
            "Timesteps",
            str(base.get("total_timesteps", 0)),
            str(opt.get("total_timesteps", 0)),
            "---",
        ),
    ]
    return "\n".join(rows)


def _dec_table(decisions):
    if not decisions:
        return "<p style='padding:20px;color:#94a3b8'>No decisions recorded.</p>"
    rows = []
    for d in reversed(decisions):
        validated = getattr(d, "was_validated", False)
        badge = (
            '<span class="badge badge-ok">Valid</span>'
            if validated
            else '<span class="badge badge-warn">Clamped</span>'
        )
        reason = getattr(d, "reason", "") or ""
        if len(reason) > 60:
            reason = reason[:57] + "..."
        ts = getattr(d, "timestamp", "")
        if hasattr(ts, "strftime"):
            ts = ts.strftime("%m-%d %H:%M")
        rows.append(
            f"<tr><td>{ts}</td><td>{getattr(d, 'timestep', '')}</td><td>{getattr(d, 'cooling_setpoint', ''):.1f}C</td><td>{getattr(d, 'heating_setpoint', ''):.1f}C</td><td>{getattr(d, 'fan_speed', ''):.2f}</td><td>{reason}</td><td>{badge}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Time</th><th>Step</th><th>Cool SP</th><th>Heat SP</th><th>Fan</th><th>Reason</th><th>Status</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def generate_dashboard(
    simulation_id=None,
    baseline_id=None,
    optimized_id=None,
    output_path="outputs/dashboard.html",
    auto_open=False,
):
    from datetime import datetime as _dt

    cfg = get_config()
    out = cfg.resolve(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    all_runs = list_simulation_runs()
    if simulation_id and not baseline_id and not optimized_id:
        run = next((r for r in all_runs if r.simulation_id == simulation_id), None)
        if run:
            if run.mode == "optimized":
                optimized_id = simulation_id
                cands = [r for r in all_runs if r.mode == "baseline" and r.total_timesteps > 0]
                if cands:
                    baseline_id = min(
                        cands, key=lambda r: abs(r.total_timesteps - run.total_timesteps)
                    ).simulation_id
            else:
                baseline_id = simulation_id
                cands = [r for r in all_runs if r.mode == "optimized" and r.total_timesteps > 0]
                if cands:
                    optimized_id = min(
                        cands, key=lambda r: abs(r.total_timesteps - run.total_timesteps)
                    ).simulation_id
        else:
            optimized_id = simulation_id
    if simulation_id and baseline_id and not optimized_id:
        optimized_id = simulation_id
    eff_opt = optimized_id or simulation_id or ""
    eff_base = baseline_id or ""
    b_df = get_metrics_dataframe(eff_base) if eff_base else pd.DataFrame()
    o_df = get_metrics_dataframe(eff_opt) if eff_opt else pd.DataFrame()
    v_df = get_violations_dataframe(eff_opt)
    cmp = compare_simulations(eff_base, eff_opt) if eff_base and eff_opt else {}
    decisions = get_recent_decisions(eff_opt, last_n=50) if eff_opt else []
    opt_s = cmp.get("optimized", cmp.get("optimised", {}))
    kwh_saved = round(cmp.get("savings_kwh", 0), 2)
    pct_saved = round(cmp.get("savings_pct", 0), 2)
    cost_saved = round(cmp.get("cost_savings", 0), 2)
    co2_saved = round(cmp.get("carbon_savings_kg", 0), 2)
    violations = opt_s.get("comfort_violations", 0)
    avg_pmv = round(opt_s.get("avg_pmv", 0), 2)
    timesteps = opt_s.get("total_timesteps", len(o_df))
    vc = P["danger"] if violations > 500 else P["warn"] if violations > 100 else P["opt"]
    pc = P["opt"] if abs(avg_pmv) <= 0.5 else P["warn"] if abs(avg_pmv) <= 1.5 else P["danger"]
    cc = cfg.simulation.comfort
    charts = dict(
        c_savings=_c_savings(cmp),
        c_hourly=_c_hourly(b_df, o_df),
        **_c_bars(cmp),
        c_energy=_c_energy(b_df, o_df),
        c_carbon=_c_carbon(b_df, o_df),
        c_breakdown=_c_breakdown(o_df),
        c_temp=_c_temp(b_df, o_df, cc.temp_min_c, cc.temp_max_c),
        c_pmv=_c_pmv(b_df, o_df),
        c_viol=_c_viol(v_df),
        c_hvac=_c_hvac(b_df, o_df),
        c_occ=_c_occ(o_df),
    )
    template = open("app/dashboard/_template.html", encoding="utf-8").read()
    html = template.format(
        opt_id=eff_opt or "---",
        base_id=eff_base or "---",
        duration=f"{timesteps} steps",
        generated=_dt.now().strftime("%Y-%m-%d %H:%M"),
        kwh_saved=kwh_saved,
        pct_saved=pct_saved,
        cost_saved=cost_saved,
        co2_saved=co2_saved,
        violations=violations,
        avg_pmv=avg_pmv,
        violations_color=vc,
        pmv_color=pc,
        comparison_rows=_cmp_rows(cmp),
        decisions_table=_dec_table(decisions),
        **charts,
    )
    out.write_text(html, encoding="utf-8")
    logger.info(f"Dashboard generated: {out} ({out.stat().st_size // 1024} KB)")
    if auto_open:
        webbrowser.open(str(out))
    return out
