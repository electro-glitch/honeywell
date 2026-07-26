"""
Pydantic schemas for MCP tool inputs and outputs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Tool Input Schemas ────────────────────────────────────────────────────────


class ReadLatestMetricsInput(BaseModel):
    simulation_id: str = Field(..., description="Simulation run identifier")


class ReadEnergyHistoryInput(BaseModel):
    simulation_id: str = Field(..., description="Simulation run identifier")
    last_n: int = Field(default=96, description="Number of recent timesteps to return")


class UpdateSetpointInput(BaseModel):
    simulation_id: str
    cooling_setpoint: float = Field(..., ge=15.0, le=35.0)
    heating_setpoint: float = Field(..., ge=10.0, le=30.0)
    fan_speed: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(default="Manual update")


class ModifyScheduleInput(BaseModel):
    simulation_id: str
    hour: int = Field(..., ge=0, le=23)
    occupancy_fraction: float = Field(..., ge=0.0, le=1.0)


class RunSimulationStepInput(BaseModel):
    simulation_id: str
    steps: int = Field(default=1, ge=1, le=100)


class RestartSimulationInput(BaseModel):
    simulation_id: str
    mode: str = Field(default="energyplus")


class GenerateDashboardInput(BaseModel):
    simulation_id: str
    output_path: str = Field(default="outputs/dashboard.html")


class SaveReportInput(BaseModel):
    simulation_id: str
    format: str = Field(default="markdown", description="'markdown' | 'html' | 'pdf' | 'csv'")
    output_path: str | None = None


# ── Tool Output Schemas ───────────────────────────────────────────────────────


class LatestMetricsOutput(BaseModel):
    simulation_id: str
    timestep: int
    timestamp: str
    indoor_temp_c: float
    outdoor_temp_c: float
    humidity_pct: float
    pmv: float
    ppd: float
    hvac_power_kw: float
    hvac_electricity_kwh: float
    lighting_electricity_kwh: float
    equipment_electricity_kwh: float
    total_electricity_kwh: float
    occupancy_fraction: float
    co2_ppm: float
    carbon_kg_co2: float
    electricity_cost: float
    cooling_setpoint_c: float
    heating_setpoint_c: float
    fan_speed: float


class EnergyHistoryPoint(BaseModel):
    timestep: int
    timestamp: str
    total_electricity_kwh: float
    hvac_electricity_kwh: float
    indoor_temp_c: float
    pmv: float
    occupancy_fraction: float
    carbon_kg_co2: float


class SetpointUpdateOutput(BaseModel):
    success: bool
    simulation_id: str
    cooling_setpoint: float
    heating_setpoint: float
    fan_speed: float
    message: str


class SimulationStepOutput(BaseModel):
    simulation_id: str
    steps_executed: int
    current_timestep: int
    message: str


class ReportOutput(BaseModel):
    success: bool
    format: str
    output_path: str
    message: str


class DashboardOutput(BaseModel):
    success: bool
    output_path: str
    message: str
