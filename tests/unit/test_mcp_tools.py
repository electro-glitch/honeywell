"""Unit tests for the MCP server tools."""

from __future__ import annotations

from datetime import datetime

from app.database.models import BuildingMetrics, SimulationRun
from app.database.repository import create_simulation_run, insert_metrics


def _seed_db(sim_id: str) -> None:
    """Seed DB with a simulation run and one metrics row."""
    run = SimulationRun(
        simulation_id=sim_id,
        mode="optimized",
        started_at=datetime.utcnow(),
    )
    create_simulation_run(run)

    m = BuildingMetrics(
        simulation_id=sim_id,
        mode="optimized",
        timestep=0,
        timestamp=datetime.utcnow(),
        indoor_temp_c=23.0,
        outdoor_temp_c=12.0,
        humidity_pct=55.0,
        pmv=0.05,
        ppd=5.1,
        hvac_electricity_kwh=2.0,
        lighting_electricity_kwh=1.0,
        equipment_electricity_kwh=0.5,
        total_electricity_kwh=3.5,
        occupancy_fraction=0.9,
        occupant_count=45,
        co2_ppm=700.0,
        hvac_power_kw=8.0,
        fan_speed=0.7,
        airflow_m3s=0.5,
        carbon_kg_co2=1.35,
        electricity_price_per_kwh=0.14,
        electricity_cost=0.49,
    )
    insert_metrics(m)


class TestMCPTools:
    """Tests for each of the 8 MCP tool functions."""

    def test_read_latest_metrics_success(self, test_config):
        from app.mcp.tools import read_latest_metrics

        sim_id = "test_mcp_001"
        _seed_db(sim_id)

        result = read_latest_metrics(sim_id)

        assert "error" not in result
        assert abs(result["indoor_temp_c"] - 23.0) < 0.01
        assert result["simulation_id"] == sim_id

    def test_read_latest_metrics_not_found(self, test_config):
        from app.mcp.tools import read_latest_metrics

        result = read_latest_metrics("nonexistent_sim_xyz")
        assert "error" in result

    def test_read_energy_history(self, test_config):
        from app.mcp.tools import read_energy_history

        sim_id = "test_mcp_002"
        _seed_db(sim_id)

        result = read_energy_history(sim_id, last_n=10)

        assert result["simulation_id"] == sim_id
        assert "history" in result
        assert result["data_points"] >= 1

    def test_update_setpoint_no_active_sim(self, test_config):
        from app.mcp.tools import update_setpoint

        result = update_setpoint(
            simulation_id="no_active_sim",
            cooling_setpoint=23.0,
            heating_setpoint=19.0,
            fan_speed=0.6,
        )
        # Should succeed even without active sim
        assert "success" in result

    def test_update_setpoint_with_active_sim(self, test_config):
        from app.energyplus.wrapper import MockSimulation, SimulationConfig
        from app.mcp.tools import register_simulation, update_setpoint

        sim_config = SimulationConfig()
        mock_sim = MockSimulation(sim_config)
        register_simulation("active_test", mock_sim)

        result = update_setpoint("active_test", 23.0, 19.0, 0.6, "test")
        assert result["success"] is True
        assert mock_sim.state.cooling_setpoint == 23.0

    def test_modify_schedule(self, test_config):
        from app.mcp.tools import modify_schedule

        result = modify_schedule("any_sim", hour=14, occupancy_fraction=0.5)
        assert result["success"] is True
        assert result["hour"] == 14

    def test_run_simulation_step(self, test_config):
        from app.mcp.tools import run_simulation_step

        result = run_simulation_step("any_sim", steps=5)
        assert result["steps_executed"] == 5

    def test_restart_simulation(self, test_config):
        from app.mcp.tools import restart_simulation

        result = restart_simulation("any_sim", mode="mock")
        assert result["success"] is True

    def test_dispatch_unknown_tool(self, test_config):
        from app.mcp.server import _dispatch_tool

        result = _dispatch_tool("nonexistent_tool", {})
        assert "error" in result
