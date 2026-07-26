"""Unit tests for the database layer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.database.db import get_db_path, init_db
from app.database.models import BuildingMetrics, ControlDecision, SimulationRun
from app.database.repository import (
    create_simulation_run,
    get_latest_metrics,
    get_metrics_history,
    get_simulation_run,
    get_simulation_summary,
    insert_decision,
    insert_metrics,
    update_simulation_run,
    get_recent_decisions,
)


# All tests use the conftest test_config fixture which monkeypatches get_db_path

class TestDatabaseInit:
    def test_init_creates_tables(self, test_config, tmp_path: Path) -> None:
        import sqlite3
        db_path = test_config.resolve(test_config.database.path)
        with sqlite3.connect(str(db_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        expected = {
            "simulation_runs",
            "building_metrics",
            "control_decisions",
            "comfort_violations",
        }
        assert expected.issubset(tables)

    def test_init_idempotent(self, test_config, tmp_path: Path) -> None:
        db_path = test_config.resolve(test_config.database.path)
        init_db(db_path)  # second call should not raise
        init_db(db_path)  # third call — idempotent


class TestSimulationRuns:
    def test_create_and_retrieve(self, test_config, sample_run):
        create_simulation_run(sample_run)
        retrieved = get_simulation_run(sample_run.simulation_id)
        assert retrieved is not None
        assert retrieved.simulation_id == sample_run.simulation_id
        assert retrieved.mode == sample_run.mode

    def test_update_run(self, test_config, sample_run):
        create_simulation_run(sample_run)
        sample_run.ended_at = datetime.utcnow()
        sample_run.total_timesteps = 100
        sample_run.total_energy_kwh = 250.5
        update_simulation_run(sample_run)

        retrieved = get_simulation_run(sample_run.simulation_id)
        assert retrieved.total_timesteps == 100
        assert abs(retrieved.total_energy_kwh - 250.5) < 0.01

    def test_get_nonexistent_returns_none(self, test_config):
        result = get_simulation_run("nonexistent_sim_999")
        assert result is None


class TestBuildingMetrics:
    def test_insert_and_retrieve(self, test_config, sample_metrics, sample_run):
        create_simulation_run(sample_run)
        insert_metrics(sample_metrics)

        latest = get_latest_metrics(sample_metrics.simulation_id)
        assert latest is not None
        assert abs(latest.indoor_temp_c - 23.5) < 0.01
        assert abs(latest.pmv - 0.1) < 0.01

    def test_get_metrics_history_limit(self, test_config, sample_run):
        create_simulation_run(sample_run)
        # Insert 5 timesteps
        for i in range(5):
            m = BuildingMetrics(
                simulation_id=sample_run.simulation_id,
                mode="baseline",
                timestep=i,
                timestamp=datetime.utcnow(),
                indoor_temp_c=22.0 + i * 0.5,
                outdoor_temp_c=15.0,
            )
            insert_metrics(m)

        history = get_metrics_history(sample_run.simulation_id, limit=3)
        assert len(history) == 3

    def test_summary_aggregation(self, test_config, sample_run):
        create_simulation_run(sample_run)
        for i in range(4):
            m = BuildingMetrics(
                simulation_id=sample_run.simulation_id,
                mode="baseline",
                timestep=i,
                timestamp=datetime.utcnow(),
                indoor_temp_c=23.0,
                outdoor_temp_c=15.0,
                total_electricity_kwh=5.0,
            )
            insert_metrics(m)

        summary = get_simulation_summary(sample_run.simulation_id)
        assert summary["total_timesteps"] == 4
        assert abs(summary["total_energy_kwh"] - 20.0) < 0.01

    def test_latest_metrics_none_for_missing_sim(self, test_config):
        result = get_latest_metrics("nonexistent_sim_xyz")
        assert result is None


class TestControlDecisions:
    def test_insert_and_retrieve(self, test_config, sample_decision, sample_run):
        create_simulation_run(sample_run)
        insert_decision(sample_decision)
        decisions = get_recent_decisions(sample_decision.simulation_id, last_n=5)
        assert len(decisions) == 1
        assert decisions[0].cooling_setpoint == 24.0
        assert decisions[0].heating_setpoint == 20.0

    def test_multiple_decisions_ordered(self, test_config, sample_run):
        create_simulation_run(sample_run)
        for i in range(3):
            d = ControlDecision(
                simulation_id=sample_run.simulation_id,
                timestep=i * 4,
                timestamp=datetime.utcnow(),
                cooling_setpoint=24.0 + i,
                heating_setpoint=20.0,
                fan_speed=0.7,
                reason=f"decision {i}",
            )
            insert_decision(d)

        decisions = get_recent_decisions(sample_run.simulation_id, last_n=10)
        assert len(decisions) == 3
        # Should be ordered by timestep ascending
        assert decisions[0].timestep < decisions[-1].timestep
