"""
Pydantic models for Eco-Loop data entities.

These are used for:
  - Validating data before database insertion
  - Serializing/deserializing records from SQLite
  - Passing structured data between modules
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class BuildingMetrics(BaseModel):
    """
    Timestep-level building performance metrics collected from EnergyPlus.
    All energy values in kWh unless noted.
    """

    id: int | None = None
    simulation_id: str = Field(..., description="Unique simulation run identifier")
    mode: str = Field(..., description="'baseline' or 'optimized'")
    timestep: int = Field(..., description="Simulation timestep index (0-based)")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Temperatures (°C)
    indoor_temp_c: float = Field(..., description="Zone air temperature (°C)")
    outdoor_temp_c: float = Field(..., description="Outdoor dry-bulb temperature (°C)")
    heating_setpoint_c: float = Field(default=20.0)
    cooling_setpoint_c: float = Field(default=24.0)

    # Humidity
    humidity_pct: float = Field(default=50.0, description="Relative humidity (%)")

    # Thermal comfort
    pmv: float = Field(default=0.0, description="Predicted Mean Vote (-3 to +3)")
    ppd: float = Field(default=5.0, description="Predicted Percentage Dissatisfied (%)")

    # Energy (kWh per timestep)
    hvac_electricity_kwh: float = Field(default=0.0)
    lighting_electricity_kwh: float = Field(default=0.0)
    equipment_electricity_kwh: float = Field(default=0.0)
    total_electricity_kwh: float = Field(default=0.0)

    # Occupancy
    occupancy_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    occupant_count: int = Field(default=0, ge=0)

    # Air quality
    co2_ppm: float = Field(default=400.0, description="CO₂ concentration (ppm)")

    # HVAC state
    hvac_power_kw: float = Field(default=0.0)
    fan_speed: float = Field(default=0.7, ge=0.0, le=1.0)
    airflow_m3s: float = Field(default=0.5, ge=0.0)

    # Carbon
    carbon_kg_co2: float = Field(default=0.0, description="CO₂ emissions this timestep")

    # Electricity pricing
    electricity_price_per_kwh: float = Field(default=0.10)
    electricity_cost: float = Field(default=0.0, description="Cost this timestep ($)")

    @field_validator("pmv")
    @classmethod
    def clamp_pmv(cls, v: float) -> float:
        return max(-3.0, min(3.0, v))

    @field_validator("humidity_pct")
    @classmethod
    def clamp_humidity(cls, v: float) -> float:
        return max(0.0, min(100.0, v))

    class Config:
        from_attributes = True


class ControlDecision(BaseModel):
    """
    A control decision produced by the LLM decision engine.
    """

    id: int | None = None
    simulation_id: str
    timestep: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Setpoints
    cooling_setpoint: float = Field(..., ge=15.0, le=35.0)
    heating_setpoint: float = Field(..., ge=10.0, le=30.0)
    fan_speed: float = Field(..., ge=0.0, le=1.0)
    airflow_m3s: float | None = Field(default=None, ge=0.0)

    # Reasoning
    reason: str = Field(..., description="LLM reasoning for this decision")
    llm_model: str = Field(default="llama3")
    raw_response: str | None = Field(default=None)

    # Validation status
    was_validated: bool = Field(default=True)
    validation_notes: str | None = None

    # Bonus: carbon-aware data
    carbon_intensity_g_kwh: float | None = None
    electricity_price_per_kwh: float | None = None

    class Config:
        from_attributes = True


class SimulationRun(BaseModel):
    """
    Metadata about a simulation run.
    """

    id: int | None = None
    simulation_id: str
    mode: str  # "baseline" | "optimized"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime | None = None
    total_timesteps: int = Field(default=0)
    total_energy_kwh: float = Field(default=0.0)
    total_cost: float = Field(default=0.0)
    total_carbon_kg: float = Field(default=0.0)
    avg_pmv: float = Field(default=0.0)
    comfort_violations: int = Field(default=0)
    llm_model: str | None = None
    config_snapshot: str | None = None  # JSON string

    class Config:
        from_attributes = True


class ComfortViolation(BaseModel):
    """
    Record of a comfort constraint violation.
    """

    id: int | None = None
    simulation_id: str
    timestep: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    violation_type: str  # "temp_high" | "temp_low" | "pmv_high" | "pmv_low" | "co2" | "humidity"
    actual_value: float
    limit_value: float
    severity: float = Field(default=0.0, description="How far outside the limit")

    class Config:
        from_attributes = True


class WeatherForecast(BaseModel):
    """Optional weather forecast data point."""

    timestamp: datetime
    outdoor_temp_c: float
    humidity_pct: float
    solar_radiation_w_m2: float = 0.0
    wind_speed_m_s: float = 0.0
    description: str = ""
