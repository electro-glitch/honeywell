"""
Optimization Control Loop
==========================
Main loop for LLM-driven building optimization.

Flow per timestep:
  1. Simulation fires callback → MetricsCollector saves to DB
  2. DecisionEngine checks if LLM query is due
  3. LLM queries metrics via MCP tools
  4. LLM returns JSON decision
  5. Validator clamps to safe ranges
  6. ActuatorController applies setpoints
  7. Simulation advances to next timestep

The loop runs synchronously inside the simulation thread.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from app.agent.decision_engine import DecisionEngine
from app.config import AppConfig, get_config
from app.database.db import init_db
from app.database.models import SimulationRun
from app.database.repository import (
    compare_simulations,
    create_simulation_run,
    get_metrics_dataframe,
    get_simulation_summary,
    update_simulation_run,
)
from app.energyplus.actuators import ActuatorController
from app.energyplus.metrics_collector import MetricsCollector
from app.energyplus.wrapper import BaseSimulation, SimulationState, create_simulation
from app.mcp.tools import register_simulation, unregister_simulation

console = Console()


class OptimizationLoop:
    """
    Orchestrates the closed-loop building optimization.

    Can run in two modes:
      - 'baseline': no LLM, just collect data with default setpoints
      - 'optimized': LLM queries and applies control decisions
    """

    def __init__(
        self,
        mode: str = "optimized",
        simulation_id: Optional[str] = None,
        config: Optional[AppConfig] = None,
    ) -> None:
        self.mode = mode
        self.simulation_id = simulation_id or f"{mode}_{uuid.uuid4().hex[:8]}"
        self.config = config or get_config()
        self._sim: Optional[BaseSimulation] = None
        self._engine: Optional[DecisionEngine] = None
        self._actuator: Optional[ActuatorController] = None
        self._run_record: Optional[SimulationRun] = None
        self._step_count = 0

        # Ensure output dirs exist
        self.config.ensure_output_dirs()

        # Initialise database
        init_db()

        logger.info(
            f"OptimizationLoop created — mode={mode}, id={self.simulation_id}"
        )

    def run(self) -> str:
        """
        Execute the full simulation run.
        Returns the simulation_id for downstream use.
        """
        # Create simulation backend
        self._sim = create_simulation(self.config.simulation)
        self._actuator = ActuatorController(self._sim)

        # Register with MCP tool system
        register_simulation(self.simulation_id, self._sim)

        # Create DB record
        self._run_record = SimulationRun(
            simulation_id=self.simulation_id,
            mode=self.mode,
            started_at=datetime.utcnow(),
            llm_model=self.config.llm.model if self.mode == "optimized" else None,
        )
        create_simulation_run(self._run_record)

        # Register callbacks
        dt_hours = 1.0 / self.config.simulation.timesteps_per_hour
        collector = MetricsCollector(
            simulation=self._sim,
            simulation_id=self.simulation_id,
            mode=self.mode,
            dt_hours=dt_hours,
        )
        self._sim.register_timestep_callback(collector)

        if self.mode == "optimized":
            self._engine = DecisionEngine(
                simulation_id=self.simulation_id,
                config=self.config.llm,
            )
            self._sim.register_timestep_callback(self._optimization_callback)
        else:
            # Baseline: apply stable defaults every timestep
            self._sim.register_timestep_callback(self._baseline_callback)

        # Run with progress display
        total_steps = (
            self.config.simulation.total_hours * self.config.simulation.timesteps_per_hour
        )
        self._display_run(total_steps)

        # Finalise
        self._finalize()
        return self.simulation_id

    def _optimization_callback(self, state: SimulationState) -> None:
        """LLM decision callback — called after metrics are saved."""
        decision = self._engine.decide(state.timestep)
        if decision is not None:
            self._actuator.apply_setpoints(
                cooling_setpoint=decision.cooling_setpoint,
                heating_setpoint=decision.heating_setpoint,
                fan_speed=decision.fan_speed,
                airflow_m3s=decision.airflow_m3s,
            )
        self._step_count = state.timestep

    def _baseline_callback(self, state: SimulationState) -> None:
        """Baseline: apply static default setpoints."""
        self._actuator.reset_to_defaults()
        self._step_count = state.timestep

    def _display_run(self, total_steps: int) -> None:
        """Run the simulation with a Rich progress bar."""
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        )

        task = progress.add_task(
            f"[{self.mode.upper()}] {self.simulation_id[:12]}",
            total=total_steps,
        )

        def _progress_callback(state: SimulationState) -> None:
            progress.update(task, completed=state.timestep + 1)

        self._sim.register_timestep_callback(_progress_callback)

        logger.info(f"Running {self.mode} simulation -- {total_steps} steps")
        try:
            with progress:
                self._sim.run_simulation(self.simulation_id)
        except Exception:
            # Progress bar render may fail on legacy Windows consoles — run without it
            self._sim.run_simulation(self.simulation_id)

    def _finalize(self) -> None:
        """Update simulation run record with final stats."""
        unregister_simulation(self.simulation_id)

        summary = get_simulation_summary(self.simulation_id)

        if self._run_record:
            self._run_record.ended_at = datetime.utcnow()
            self._run_record.total_timesteps = summary.get("total_timesteps", 0)
            self._run_record.total_energy_kwh = summary.get("total_energy_kwh", 0.0)
            self._run_record.total_cost = summary.get("total_cost", 0.0)
            self._run_record.total_carbon_kg = summary.get("total_carbon_kg", 0.0)
            self._run_record.avg_pmv = summary.get("avg_pmv", 0.0)
            self._run_record.comfort_violations = summary.get("comfort_violations", 0)
            update_simulation_run(self._run_record)

        duration = (
            self._run_record.ended_at - self._run_record.started_at
            if self._run_record and self._run_record.ended_at
            else None
        )

        try:
            console.print(
                Panel(
                    f"[green]Simulation complete![/green]\n"
                    f"ID: {self.simulation_id}\n"
                    f"Steps: {summary.get('total_timesteps', 0)}\n"
                    f"Energy: {summary.get('total_energy_kwh', 0):.2f} kWh\n"
                    f"Comfort violations: {summary.get('comfort_violations', 0)}\n"
                    f"Duration: {duration}",
                    title=f"Eco-Loop -- {self.mode.upper()}",
                    border_style="green",
                )
            )
        except Exception:
            logger.info(
                f"Simulation {self.simulation_id} complete -- "
                f"energy={summary.get('total_energy_kwh', 0):.2f} kWh"
            )


        # Export CSV
        self._export_csv()

        # Engine stats
        if self._engine:
            stats = self._engine.get_stats()
            logger.info(f"Decision engine stats: {stats}")

    def _export_csv(self) -> None:
        """Export metrics to CSV for later comparison."""
        df = get_metrics_dataframe(self.simulation_id)
        if df.empty:
            return

        cfg = self.config.output
        if self.mode == "baseline":
            out_path = self.config.resolve(cfg.baseline_csv)
        else:
            out_path = self.config.resolve(cfg.optimized_csv)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(str(out_path), index=False)
        logger.info(f"Exported {len(df)} rows → {out_path}")


def run_comparison(
    config: Optional[AppConfig] = None,
) -> tuple[str, str]:
    """
    Run both baseline and optimized simulations sequentially,
    then produce a comparison CSV.

    Returns (baseline_id, optimized_id).
    """
    cfg = config or get_config()

    console.rule("[bold cyan]Eco-Loop -- Baseline Run")
    baseline_loop = OptimizationLoop(mode="baseline", config=cfg)
    baseline_id = baseline_loop.run()

    console.rule("[bold cyan]Eco-Loop -- Optimization Run")
    opt_loop = OptimizationLoop(mode="optimized", config=cfg)
    optimized_id = opt_loop.run()

    # Comparison
    comparison = compare_simulations(baseline_id, optimized_id)
    _save_comparison_csv(comparison, cfg)

    console.print(
        Panel(
            f"[bold]Comparison Summary[/bold]\n"
            f"Energy savings: {comparison.get('savings_kwh', 0):.2f} kWh "
            f"({comparison.get('savings_pct', 0):.1f}%)\n"
            f"Cost savings: ${comparison.get('cost_savings', 0):.2f}\n"
            f"Carbon savings: {comparison.get('carbon_savings_kg', 0):.2f} kg CO2",
            title="Results",
            border_style="cyan",
        )
    )

    return baseline_id, optimized_id


def _save_comparison_csv(comparison: dict, config: AppConfig) -> None:
    """Save baseline vs optimized comparison to CSV."""
    out_path = config.resolve(config.output.comparison_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for key, vals in [
        ("baseline", comparison.get("baseline", {})),
        ("optimized", comparison.get("optimized", {})),
    ]:
        row = {"mode": key, **vals}
        rows.append(row)

    if rows:
        pd.DataFrame(rows).to_csv(str(out_path), index=False)
        logger.info(f"Comparison CSV → {out_path}")
