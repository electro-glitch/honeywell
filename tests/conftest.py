"""
Shared pytest fixtures for Eco-Loop tests.
Provides an in-memory database, mock simulation, and config overrides.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

import pytest

from app.database.db import init_db
from app.database.models import BuildingMetrics, ControlDecision, SimulationRun
from app.energyplus.wrapper import MockSimulation


# ── Config ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Create a fresh temporary SQLite database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


@pytest.fixture()
def test_config(tmp_path: Path, monkeypatch):
    """Return a minimal test AppConfig pointing at temp directory."""
    from app.config import (
        AppConfig, SimulationConfig, LLMConfig, DatabaseConfig,
        OutputConfig, LoggingConfig,
    )
    db_path = tmp_path / "test.db"
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    (out_dir / "reports").mkdir()
    (out_dir / "plots").mkdir()
    (tmp_path / "data").mkdir()

    cfg = AppConfig(
        simulation=SimulationConfig(
            mode="mock",
            timesteps_per_hour=4,
            total_hours=1,  # 4 timesteps total
        ),
        llm=LLMConfig(
            provider="ollama",
            model="llama3",
            query_every_n_steps=2,
            max_attempts=1,
        ),
        database=DatabaseConfig(path=str(db_path)),
        output=OutputConfig(
            dir=str(out_dir),
            reports_dir=str(out_dir / "reports"),
            plots_dir=str(out_dir / "plots"),
            baseline_csv=str(out_dir / "baseline.csv"),
            optimized_csv=str(out_dir / "optimized.csv"),
            comparison_csv=str(out_dir / "comparison.csv"),
            dashboard_html=str(out_dir / "dashboard.html"),
        ),
        logging=LoggingConfig(level="WARNING"),
    )

    # Patch get_config to return this config everywhere
    import app.database.db as db_mod
    monkeypatch.setattr(db_mod, "get_db_path", lambda: db_path)
    init_db(db_path)

    return cfg


# ── Simulation ────────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_sim(test_config) -> MockSimulation:
    return MockSimulation(test_config.simulation)


# ── Sample Data ───────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_metrics() -> BuildingMetrics:
    return BuildingMetrics(
        simulation_id="test_sim_001",
        mode="baseline",
        timestep=0,
        timestamp=datetime.utcnow(),
        indoor_temp_c=23.5,
        outdoor_temp_c=15.0,
        humidity_pct=50.0,
        pmv=0.1,
        ppd=5.5,
        hvac_electricity_kwh=2.5,
        lighting_electricity_kwh=1.0,
        equipment_electricity_kwh=0.8,
        total_electricity_kwh=4.3,
        occupancy_fraction=0.8,
        occupant_count=40,
        co2_ppm=650.0,
        hvac_power_kw=10.0,
        fan_speed=0.7,
        airflow_m3s=0.5,
        carbon_kg_co2=1.66,
        electricity_price_per_kwh=0.14,
        electricity_cost=0.602,
    )


@pytest.fixture()
def sample_decision() -> ControlDecision:
    return ControlDecision(
        simulation_id="test_sim_001",
        timestep=4,
        timestamp=datetime.utcnow(),
        cooling_setpoint=24.0,
        heating_setpoint=20.0,
        fan_speed=0.7,
        airflow_m3s=0.5,
        reason="Test decision",
        llm_model="llama3",
    )


@pytest.fixture()
def sample_run() -> SimulationRun:
    return SimulationRun(
        simulation_id="test_sim_001",
        mode="baseline",
        started_at=datetime.utcnow(),
        total_timesteps=4,
        total_energy_kwh=100.0,
    )
