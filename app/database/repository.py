"""
High-level database repository functions for Eco-Loop.

All database I/O goes through this module.
Supports both synchronous (for EnergyPlus callback thread) and async.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from loguru import logger

from app.database.db import get_sync_db
from app.database.models import (
    BuildingMetrics,
    ComfortViolation,
    ControlDecision,
    SimulationRun,
)

# ── Simulation Runs ──────────────────────────────────────────────────────────


def create_simulation_run(run: SimulationRun) -> None:
    """Insert a new simulation run record."""
    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO simulation_runs
                (simulation_id, mode, started_at, ended_at, total_timesteps,
                 total_energy_kwh, total_cost, total_carbon_kg, avg_pmv,
                 comfort_violations, llm_model, config_snapshot)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run.simulation_id,
                run.mode,
                run.started_at.isoformat(),
                run.ended_at.isoformat() if run.ended_at else None,
                run.total_timesteps,
                run.total_energy_kwh,
                run.total_cost,
                run.total_carbon_kg,
                run.avg_pmv,
                run.comfort_violations,
                run.llm_model,
                run.config_snapshot,
            ),
        )
    logger.debug(f"Created simulation run {run.simulation_id}")


def update_simulation_run(run: SimulationRun) -> None:
    """Update an existing simulation run with final stats."""
    with get_sync_db() as conn:
        conn.execute(
            """
            UPDATE simulation_runs SET
                ended_at = ?,
                total_timesteps = ?,
                total_energy_kwh = ?,
                total_cost = ?,
                total_carbon_kg = ?,
                avg_pmv = ?,
                comfort_violations = ?
            WHERE simulation_id = ?
            """,
            (
                run.ended_at.isoformat() if run.ended_at else None,
                run.total_timesteps,
                run.total_energy_kwh,
                run.total_cost,
                run.total_carbon_kg,
                run.avg_pmv,
                run.comfort_violations,
                run.simulation_id,
            ),
        )
    logger.debug(f"Updated simulation run {run.simulation_id}")


def get_simulation_run(simulation_id: str) -> SimulationRun | None:
    """Fetch a simulation run by ID."""
    with get_sync_db() as conn:
        row = conn.execute(
            "SELECT * FROM simulation_runs WHERE simulation_id = ?", (simulation_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["started_at"] = datetime.fromisoformat(d["started_at"])
    if d["ended_at"]:
        d["ended_at"] = datetime.fromisoformat(d["ended_at"])
    return SimulationRun(**d)


def list_simulation_runs() -> list[SimulationRun]:
    """List all simulation runs ordered by start time."""
    with get_sync_db() as conn:
        rows = conn.execute("SELECT * FROM simulation_runs ORDER BY started_at DESC").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["started_at"] = datetime.fromisoformat(d["started_at"])
        if d["ended_at"]:
            d["ended_at"] = datetime.fromisoformat(d["ended_at"])
        result.append(SimulationRun(**d))
    return result


# ── Building Metrics ─────────────────────────────────────────────────────────


def insert_metrics(m: BuildingMetrics) -> None:
    """Insert one timestep of building metrics."""
    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO building_metrics
                (simulation_id, mode, timestep, timestamp,
                 indoor_temp_c, outdoor_temp_c, heating_setpoint_c, cooling_setpoint_c,
                 humidity_pct, pmv, ppd,
                 hvac_electricity_kwh, lighting_electricity_kwh, equipment_electricity_kwh,
                 total_electricity_kwh,
                 occupancy_fraction, occupant_count, co2_ppm,
                 hvac_power_kw, fan_speed, airflow_m3s,
                 carbon_kg_co2, electricity_price_per_kwh, electricity_cost)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                m.simulation_id,
                m.mode,
                m.timestep,
                m.timestamp.isoformat(),
                m.indoor_temp_c,
                m.outdoor_temp_c,
                m.heating_setpoint_c,
                m.cooling_setpoint_c,
                m.humidity_pct,
                m.pmv,
                m.ppd,
                m.hvac_electricity_kwh,
                m.lighting_electricity_kwh,
                m.equipment_electricity_kwh,
                m.total_electricity_kwh,
                m.occupancy_fraction,
                m.occupant_count,
                m.co2_ppm,
                m.hvac_power_kw,
                m.fan_speed,
                m.airflow_m3s,
                m.carbon_kg_co2,
                m.electricity_price_per_kwh,
                m.electricity_cost,
            ),
        )


def get_latest_metrics(simulation_id: str) -> BuildingMetrics | None:
    """Return the most recent metrics row for a simulation."""
    with get_sync_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM building_metrics
            WHERE simulation_id = ?
            ORDER BY timestep DESC LIMIT 1
            """,
            (simulation_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_metrics(dict(row))


def get_metrics_history(
    simulation_id: str,
    limit: int = 200,
    offset: int = 0,
) -> list[BuildingMetrics]:
    """Return ordered metrics history for a simulation."""
    with get_sync_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM building_metrics
            WHERE simulation_id = ?
            ORDER BY timestep ASC
            LIMIT ? OFFSET ?
            """,
            (simulation_id, limit, offset),
        ).fetchall()
    return [_row_to_metrics(dict(r)) for r in rows]


def get_metrics_dataframe(simulation_id: str) -> pd.DataFrame:
    """Load all metrics for a simulation into a Pandas DataFrame."""
    with get_sync_db() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM building_metrics WHERE simulation_id = ? ORDER BY timestep",
            conn,
            params=(simulation_id,),
        )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def get_energy_history(simulation_id: str, last_n: int = 96) -> list[dict]:
    """Return recent energy history as list of dicts (for MCP tool)."""
    with get_sync_db() as conn:
        rows = conn.execute(
            """
            SELECT timestep, timestamp, total_electricity_kwh, hvac_electricity_kwh,
                   indoor_temp_c, pmv, occupancy_fraction, carbon_kg_co2
            FROM building_metrics
            WHERE simulation_id = ?
            ORDER BY timestep DESC LIMIT ?
            """,
            (simulation_id, last_n),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def _row_to_metrics(d: dict) -> BuildingMetrics:
    d["timestamp"] = datetime.fromisoformat(d["timestamp"])
    return BuildingMetrics(**d)


# ── Control Decisions ────────────────────────────────────────────────────────


def insert_decision(decision: ControlDecision) -> None:
    """Save an LLM control decision."""
    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO control_decisions
                (simulation_id, timestep, timestamp,
                 cooling_setpoint, heating_setpoint, fan_speed, airflow_m3s,
                 reason, llm_model, raw_response, was_validated, validation_notes,
                 carbon_intensity_g_kwh, electricity_price_per_kwh)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                decision.simulation_id,
                decision.timestep,
                decision.timestamp.isoformat(),
                decision.cooling_setpoint,
                decision.heating_setpoint,
                decision.fan_speed,
                decision.airflow_m3s,
                decision.reason,
                decision.llm_model,
                decision.raw_response,
                int(decision.was_validated),
                decision.validation_notes,
                decision.carbon_intensity_g_kwh,
                decision.electricity_price_per_kwh,
            ),
        )


def get_recent_decisions(simulation_id: str, last_n: int = 10) -> list[ControlDecision]:
    """Get recent control decisions for a simulation."""
    with get_sync_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM control_decisions
            WHERE simulation_id = ?
            ORDER BY timestep DESC LIMIT ?
            """,
            (simulation_id, last_n),
        ).fetchall()
    return [_row_to_decision(dict(r)) for r in reversed(rows)]


def _row_to_decision(d: dict) -> ControlDecision:
    d["timestamp"] = datetime.fromisoformat(d["timestamp"])
    d["was_validated"] = bool(d["was_validated"])
    return ControlDecision(**d)


# ── Comfort Violations ───────────────────────────────────────────────────────


def insert_violation(v: ComfortViolation) -> None:
    """Record a comfort constraint violation."""
    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO comfort_violations
                (simulation_id, timestep, timestamp, violation_type,
                 actual_value, limit_value, severity)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                v.simulation_id,
                v.timestep,
                v.timestamp.isoformat(),
                v.violation_type,
                v.actual_value,
                v.limit_value,
                v.severity,
            ),
        )


def get_violation_count(simulation_id: str) -> int:
    """Return the number of comfort violations for a simulation."""
    with get_sync_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM comfort_violations WHERE simulation_id = ?",
            (simulation_id,),
        ).fetchone()
    return row["cnt"] if row else 0


def get_violations_dataframe(simulation_id: str) -> pd.DataFrame:
    """Load all violations into a DataFrame."""
    with get_sync_db() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM comfort_violations WHERE simulation_id = ? ORDER BY timestep",
            conn,
            params=(simulation_id,),
        )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


# ── Summary Stats ────────────────────────────────────────────────────────────


def get_simulation_summary(simulation_id: str) -> dict:
    """Compute aggregate summary statistics for a simulation."""
    with get_sync_db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total_timesteps,
                SUM(total_electricity_kwh) as total_energy_kwh,
                SUM(electricity_cost) as total_cost,
                SUM(carbon_kg_co2) as total_carbon_kg,
                AVG(pmv) as avg_pmv,
                AVG(indoor_temp_c) as avg_temp_c,
                MAX(hvac_power_kw) as peak_hvac_kw,
                AVG(hvac_electricity_kwh) as avg_hvac_kwh,
                MIN(indoor_temp_c) as min_temp_c,
                MAX(indoor_temp_c) as max_temp_c
            FROM building_metrics WHERE simulation_id = ?
            """,
            (simulation_id,),
        ).fetchone()
        violations = conn.execute(
            "SELECT COUNT(*) as cnt FROM comfort_violations WHERE simulation_id = ?",
            (simulation_id,),
        ).fetchone()

    if row is None:
        return {}

    return {
        **dict(row),
        "comfort_violations": violations["cnt"] if violations else 0,
        "simulation_id": simulation_id,
    }


def compare_simulations(baseline_id: str, optimized_id: str) -> dict:
    """Compare baseline vs optimized simulation statistics."""
    base = get_simulation_summary(baseline_id)
    opt = get_simulation_summary(optimized_id)

    if not base or not opt:
        return {"error": "One or both simulations not found"}

    baseline_energy = base.get("total_energy_kwh", 1.0) or 1.0
    savings_kwh = baseline_energy - opt.get("total_energy_kwh", 0)
    savings_pct = (savings_kwh / baseline_energy) * 100

    return {
        "baseline": base,
        "optimized": opt,
        "savings_kwh": savings_kwh,
        "savings_pct": savings_pct,
        "cost_savings": base.get("total_cost", 0) - opt.get("total_cost", 0),
        "carbon_savings_kg": base.get("total_carbon_kg", 0) - opt.get("total_carbon_kg", 0),
        "comfort_improvement": (
            opt.get("comfort_violations", 0) - base.get("comfort_violations", 0)
        ),
    }
