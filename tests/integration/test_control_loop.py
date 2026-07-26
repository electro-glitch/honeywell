"""
Integration tests for the full control loop.
Runs the mock simulation end-to-end with a tiny config (1 hour, 4 timesteps).
Uses monkeypatched DB from conftest.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import AppConfig


class TestBaselineLoop:
    def test_baseline_runs_and_saves_metrics(self, test_config: AppConfig):
        """Full baseline run produces metrics in the database."""
        from app.controllers.control_loop import OptimizationLoop
        loop = OptimizationLoop(mode="baseline", config=test_config)
        sim_id = loop.run()

        from app.database.repository import get_metrics_history, get_simulation_summary
        history = get_metrics_history(sim_id, limit=100)
        assert len(history) > 0, "No metrics saved during baseline run"

        summary = get_simulation_summary(sim_id)
        assert summary["total_timesteps"] > 0
        assert summary["total_energy_kwh"] > 0

    def test_baseline_exports_csv(self, test_config: AppConfig):
        """Baseline run should export a CSV file."""
        from app.controllers.control_loop import OptimizationLoop
        loop = OptimizationLoop(mode="baseline", config=test_config)
        loop.run()

        csv_path = test_config.resolve(test_config.output.baseline_csv)
        assert csv_path.exists(), f"Baseline CSV not found at {csv_path}"
        content = csv_path.read_text()
        assert "indoor_temp_c" in content

    def test_baseline_metrics_have_valid_pmv(self, test_config: AppConfig):
        """PMV values should be within [-3, 3]."""
        from app.controllers.control_loop import OptimizationLoop
        loop = OptimizationLoop(mode="baseline", config=test_config)
        sim_id = loop.run()

        from app.database.repository import get_metrics_history
        history = get_metrics_history(sim_id, limit=100)
        assert all(-3.0 <= m.pmv <= 3.0 for m in history)

    def test_baseline_energy_values_non_negative(self, test_config: AppConfig):
        """Energy values should all be non-negative."""
        from app.controllers.control_loop import OptimizationLoop
        loop = OptimizationLoop(mode="baseline", config=test_config)
        sim_id = loop.run()

        from app.database.repository import get_metrics_history
        history = get_metrics_history(sim_id, limit=100)
        for m in history:
            assert m.total_electricity_kwh >= 0
            assert m.hvac_electricity_kwh >= 0
            assert m.carbon_kg_co2 >= 0


class TestOptimizedLoop:
    def test_optimized_runs_with_stub_llm(self, test_config: AppConfig):
        """Optimized run uses StubLLMClient and saves decisions."""
        from app.agent.llm_client import StubLLMClient
        with patch("app.agent.decision_engine.create_llm_client", return_value=StubLLMClient()):
            from app.controllers.control_loop import OptimizationLoop
            loop = OptimizationLoop(mode="optimized", config=test_config)
            sim_id = loop.run()

        from app.database.repository import get_metrics_history
        history = get_metrics_history(sim_id, limit=100)
        assert len(history) > 0

        from app.database.repository import get_recent_decisions
        decisions = get_recent_decisions(sim_id, last_n=20)
        assert len(decisions) >= 1, "Expected at least 1 LLM decision"

    def test_setpoints_applied_are_within_bounds(self, test_config: AppConfig):
        """All setpoints in DB should be within safety bounds."""
        from app.agent.llm_client import StubLLMClient
        with patch("app.agent.decision_engine.create_llm_client", return_value=StubLLMClient()):
            from app.controllers.control_loop import OptimizationLoop
            loop = OptimizationLoop(mode="optimized", config=test_config)
            sim_id = loop.run()

        from app.database.repository import get_recent_decisions
        decisions = get_recent_decisions(sim_id, last_n=50)
        for d in decisions:
            assert 15.0 <= d.cooling_setpoint <= 35.0, f"cooling {d.cooling_setpoint} OOB"
            assert 10.0 <= d.heating_setpoint <= 30.0, f"heating {d.heating_setpoint} OOB"
            assert 0.0 <= d.fan_speed <= 1.0, f"fan {d.fan_speed} OOB"

    def test_optimized_exports_csv(self, test_config: AppConfig):
        """Optimized run exports optimized.csv."""
        from app.agent.llm_client import StubLLMClient
        with patch("app.agent.decision_engine.create_llm_client", return_value=StubLLMClient()):
            from app.controllers.control_loop import OptimizationLoop
            loop = OptimizationLoop(mode="optimized", config=test_config)
            loop.run()

        csv_path = test_config.resolve(test_config.output.optimized_csv)
        assert csv_path.exists()
