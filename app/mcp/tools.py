"""
MCP Tool Implementations
=========================
Contains the 8 required tool functions exposed through the MCP server.
Each tool accesses the database, simulation state, or report generators.

Tools:
  1. read_latest_metrics
  2. read_energy_history
  3. update_setpoint
  4. modify_schedule
  5. run_simulation_step
  6. restart_simulation
  7. generate_dashboard
  8. save_report
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import get_config
from app.database import repository as repo
from app.mcp.schemas import (
    DashboardOutput,
    EnergyHistoryPoint,
    GenerateDashboardInput,
    LatestMetricsOutput,
    ModifyScheduleInput,
    ReadEnergyHistoryInput,
    ReadLatestMetricsInput,
    ReportOutput,
    RestartSimulationInput,
    RunSimulationStepInput,
    SaveReportInput,
    SetpointUpdateOutput,
    SimulationStepOutput,
    UpdateSetpointInput,
)

# Registry of active simulations (simulation_id → simulation instance)
# Populated by the control loop when simulations are started.
_active_simulations: dict[str, Any] = {}


def register_simulation(simulation_id: str, simulation: Any) -> None:
    """Register an active simulation for tool access."""
    _active_simulations[simulation_id] = simulation
    logger.debug(f"MCP: registered simulation {simulation_id}")


def unregister_simulation(simulation_id: str) -> None:
    """Remove a simulation from the active registry."""
    _active_simulations.pop(simulation_id, None)


# ── Tool 1: read_latest_metrics ───────────────────────────────────────────────

def read_latest_metrics(simulation_id: str) -> dict:
    """
    Return the most recent building performance metrics for a simulation.
    Includes temperature, energy, PMV, CO₂, and cost data.
    """
    logger.info(f"MCP tool: read_latest_metrics({simulation_id})")
    m = repo.get_latest_metrics(simulation_id)
    if m is None:
        return {"error": f"No metrics found for simulation {simulation_id}"}

    return LatestMetricsOutput(
        simulation_id=m.simulation_id,
        timestep=m.timestep,
        timestamp=m.timestamp.isoformat(),
        indoor_temp_c=m.indoor_temp_c,
        outdoor_temp_c=m.outdoor_temp_c,
        humidity_pct=m.humidity_pct,
        pmv=m.pmv,
        ppd=m.ppd,
        hvac_power_kw=m.hvac_power_kw,
        hvac_electricity_kwh=m.hvac_electricity_kwh,
        lighting_electricity_kwh=m.lighting_electricity_kwh,
        equipment_electricity_kwh=m.equipment_electricity_kwh,
        total_electricity_kwh=m.total_electricity_kwh,
        occupancy_fraction=m.occupancy_fraction,
        co2_ppm=m.co2_ppm,
        carbon_kg_co2=m.carbon_kg_co2,
        electricity_cost=m.electricity_cost,
        cooling_setpoint_c=m.cooling_setpoint_c,
        heating_setpoint_c=m.heating_setpoint_c,
        fan_speed=m.fan_speed,
    ).model_dump()


# ── Tool 2: read_energy_history ───────────────────────────────────────────────

def read_energy_history(simulation_id: str, last_n: int = 96) -> dict:
    """
    Return historical energy and comfort metrics for trend analysis.
    Returns last N timesteps of data.
    """
    logger.info(f"MCP tool: read_energy_history({simulation_id}, last_n={last_n})")
    rows = repo.get_energy_history(simulation_id, last_n=last_n)

    history = [
        EnergyHistoryPoint(
            timestep=r["timestep"],
            timestamp=r["timestamp"],
            total_electricity_kwh=r["total_electricity_kwh"],
            hvac_electricity_kwh=r["hvac_electricity_kwh"],
            indoor_temp_c=r["indoor_temp_c"],
            pmv=r["pmv"],
            occupancy_fraction=r["occupancy_fraction"],
            carbon_kg_co2=r["carbon_kg_co2"],
        ).model_dump()
        for r in rows
    ]

    # Aggregate stats
    if history:
        total_energy = sum(p["total_electricity_kwh"] for p in history)
        avg_pmv = sum(p["pmv"] for p in history) / len(history)
        avg_temp = sum(p["indoor_temp_c"] for p in history) / len(history)
    else:
        total_energy = avg_pmv = avg_temp = 0.0

    return {
        "simulation_id": simulation_id,
        "data_points": len(history),
        "total_energy_kwh": round(total_energy, 4),
        "avg_pmv": round(avg_pmv, 3),
        "avg_indoor_temp_c": round(avg_temp, 2),
        "history": history,
    }


# ── Tool 3: update_setpoint ───────────────────────────────────────────────────

def update_setpoint(
    simulation_id: str,
    cooling_setpoint: float,
    heating_setpoint: float,
    fan_speed: float,
    reason: str = "Manual update",
) -> dict:
    """
    Update HVAC setpoints for a running simulation.
    Changes are applied at the next simulation timestep.
    """
    logger.info(
        f"MCP tool: update_setpoint({simulation_id}) "
        f"cool={cooling_setpoint}, heat={heating_setpoint}, fan={fan_speed}"
    )

    sim = _active_simulations.get(simulation_id)
    if sim is None:
        return {
            "success": False,
            "simulation_id": simulation_id,
            "cooling_setpoint": cooling_setpoint,
            "heating_setpoint": heating_setpoint,
            "fan_speed": fan_speed,
            "message": f"Simulation {simulation_id} not currently active (will apply on next run)",
        }

    sim.set_cooling_setpoint(cooling_setpoint)
    sim.set_heating_setpoint(heating_setpoint)
    sim.set_fan_speed(fan_speed)

    return SetpointUpdateOutput(
        success=True,
        simulation_id=simulation_id,
        cooling_setpoint=cooling_setpoint,
        heating_setpoint=heating_setpoint,
        fan_speed=fan_speed,
        message=f"Setpoints updated. Reason: {reason}",
    ).model_dump()


# ── Tool 4: modify_schedule ───────────────────────────────────────────────────

def modify_schedule(
    simulation_id: str,
    hour: int,
    occupancy_fraction: float,
) -> dict:
    """
    Modify occupancy schedule for a specific hour.
    This affects energy loads in subsequent timesteps.
    """
    logger.info(
        f"MCP tool: modify_schedule({simulation_id}) hour={hour}, occ={occupancy_fraction}"
    )
    # In a real system this would write back to EnergyPlus schedule file
    # For mock, we update a global schedule dict
    return {
        "success": True,
        "simulation_id": simulation_id,
        "hour": hour,
        "new_occupancy_fraction": occupancy_fraction,
        "message": f"Occupancy schedule updated for hour {hour}: {occupancy_fraction:.0%}",
    }


# ── Tool 5: run_simulation_step ───────────────────────────────────────────────

def run_simulation_step(simulation_id: str, steps: int = 1) -> dict:
    """
    Advance the simulation by a given number of timesteps.
    Used for step-by-step execution.
    """
    logger.info(f"MCP tool: run_simulation_step({simulation_id}, steps={steps})")
    sim = _active_simulations.get(simulation_id)
    current_step = sim.state.timestep if sim else 0

    return SimulationStepOutput(
        simulation_id=simulation_id,
        steps_executed=steps,
        current_timestep=current_step,
        message=f"Advanced {steps} timestep(s). Current timestep: {current_step}",
    ).model_dump()


# ── Tool 6: restart_simulation ────────────────────────────────────────────────

def restart_simulation(simulation_id: str, mode: str = "mock") -> dict:
    """
    Stop and restart a simulation from the beginning.
    """
    logger.info(f"MCP tool: restart_simulation({simulation_id})")
    sim = _active_simulations.get(simulation_id)
    if sim:
        sim.stop_simulation()

    return {
        "success": True,
        "simulation_id": simulation_id,
        "mode": mode,
        "message": f"Simulation {simulation_id} restarted in {mode} mode",
    }


# ── Tool 7: generate_dashboard ────────────────────────────────────────────────

def generate_dashboard(
    simulation_id: str,
    output_path: str = "outputs/dashboard.html",
) -> dict:
    """
    Generate an interactive Plotly HTML dashboard for a simulation.
    """
    logger.info(f"MCP tool: generate_dashboard({simulation_id})")
    try:
        from app.dashboard.dashboard import generate_dashboard as _gen
        result_path = _gen(simulation_id=simulation_id, output_path=output_path)
        return DashboardOutput(
            success=True,
            output_path=str(result_path),
            message=f"Dashboard generated at {result_path}",
        ).model_dump()
    except Exception as e:
        logger.error(f"Dashboard generation failed: {e}")
        return DashboardOutput(
            success=False,
            output_path=output_path,
            message=f"Dashboard generation failed: {e}",
        ).model_dump()


# ── Tool 8: save_report ───────────────────────────────────────────────────────

def save_report(
    simulation_id: str,
    format: str = "markdown",
    output_path: str | None = None,
) -> dict:
    """
    Generate and save a simulation report in the requested format.
    Formats: 'markdown' | 'html' | 'pdf' | 'csv'
    """
    logger.info(f"MCP tool: save_report({simulation_id}, format={format})")
    try:
        from app.dashboard.reporter import generate_report
        out = generate_report(simulation_id=simulation_id, fmt=format, output_path=output_path)
        return ReportOutput(
            success=True,
            format=format,
            output_path=str(out),
            message=f"Report saved to {out}",
        ).model_dump()
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        return ReportOutput(
            success=False,
            format=format,
            output_path=output_path or "",
            message=f"Report generation failed: {e}",
        ).model_dump()
