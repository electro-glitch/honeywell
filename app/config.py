"""
Configuration management for Eco-Loop.

Loads YAML configs and environment variables, merges them into a single
Settings object accessible throughout the application.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env if present
load_dotenv()

_PROJECT_ROOT = Path(__file__).parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return as dict. Returns empty dict if not found."""
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


# ── Sub-models ──────────────────────────────────────────────────────────────


class HVACConstraints(BaseModel):
    cooling_setpoint_min: float = 18.0
    cooling_setpoint_max: float = 28.0
    cooling_setpoint_default: float = 24.0
    heating_setpoint_min: float = 15.0
    heating_setpoint_max: float = 28.0
    heating_setpoint_default: float = 20.0
    fan_speed_min: float = 0.0
    fan_speed_max: float = 1.0
    fan_speed_default: float = 0.7
    airflow_min: float = 0.0
    airflow_max: float = 10.0
    airflow_default: float = 0.5


class ComfortConstraints(BaseModel):
    pmv_min: float = -0.5
    pmv_max: float = 0.5
    temp_min_c: float = 22.0
    temp_max_c: float = 25.0
    co2_max_ppm: float = 1000.0
    humidity_min: float = 30.0
    humidity_max: float = 70.0


class SimulationConfig(BaseModel):
    mode: str = "energyplus"  # "mock" | "energyplus"
    timesteps_per_hour: int = 6
    total_hours: int = 4380
    idf_file: str = "data/idf/ZoneCoupledKivaRefBldgMediumOffice.idf"
    epw_file: str = "data/weather/IND_DL_New.Delhi-Gandhi.Intl.AP.421810_TMYx.2004-2018.epw"
    energyplus_dir: str = "C:/EnergyPlusV26-1-0"
    hvac: HVACConstraints = Field(default_factory=HVACConstraints)
    comfort: ComfortConstraints = Field(default_factory=ComfortConstraints)


class LLMConfig(BaseModel):
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "llama3"
    temperature: float = 0.2
    top_p: float = 0.9
    max_tokens: int = 1024
    timeout: int = 120
    max_attempts: int = 3
    wait_seconds: float = 2.0
    query_every_n_steps: int = 4
    always_reason: bool = False
    temp_drift_threshold: float = 0.5
    memory_size: int = 20


class DatabaseConfig(BaseModel):
    path: str = "data/eco_loop.db"
    max_metrics_rows: int = 100_000


class MCPConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    transport: str = "stdio"


class OutputConfig(BaseModel):
    dir: str = "outputs"
    reports_dir: str = "outputs/reports"
    plots_dir: str = "outputs/plots"
    baseline_csv: str = "outputs/baseline.csv"
    optimized_csv: str = "outputs/optimized.csv"
    comparison_csv: str = "outputs/comparison.csv"
    dashboard_html: str = "outputs/dashboard.html"
    report_md: str = "outputs/reports/report.md"
    report_html: str = "outputs/reports/report.html"
    report_pdf: str = "outputs/reports/report.pdf"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "outputs/eco_loop.log"
    rotation: str = "10 MB"
    retention: str = "30 days"


class PricingConfig(BaseModel):
    off_peak: float = 0.08
    mid_peak: float = 0.14
    on_peak: float = 0.22
    peak_hours: list[int] = Field(default_factory=lambda: [9, 10, 11, 17, 18, 19])
    mid_peak_hours: list[int] = Field(default_factory=lambda: [7, 8, 12, 13, 14, 15, 16])


class CarbonConfig(BaseModel):
    intensity_g_per_kwh: float = 386.0
    realtime_enabled: bool = False


class AppConfig(BaseModel):
    """Merged application configuration."""

    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    carbon: CarbonConfig = Field(default_factory=CarbonConfig)

    def get_project_root(self) -> Path:
        return _PROJECT_ROOT

    def resolve(self, path: str) -> Path:
        """Resolve a relative path against the project root."""
        p = Path(path)
        if p.is_absolute():
            return p
        return _PROJECT_ROOT / p

    def ensure_output_dirs(self) -> None:
        """Create all output directories."""
        for attr in [
            self.output.dir,
            self.output.reports_dir,
            self.output.plots_dir,
        ]:
            self.resolve(attr).mkdir(parents=True, exist_ok=True)
        # Also ensure data dir
        (self.resolve("data")).mkdir(parents=True, exist_ok=True)
        (self.resolve("data/idf")).mkdir(parents=True, exist_ok=True)
        (self.resolve("data/weather")).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Load and cache the application configuration."""
    cfg_dir = _PROJECT_ROOT / "configs"

    sim_raw = _load_yaml(cfg_dir / "simulation.yaml")
    llm_raw = _load_yaml(cfg_dir / "llm.yaml")
    settings_raw = _load_yaml(cfg_dir / "settings.yaml")

    # Extract nested sections
    sim_section = sim_raw.get("simulation", {})
    hvac_section = sim_raw.get("hvac", {})
    comfort_section = sim_raw.get("comfort", {})
    pricing_section = sim_raw.get("pricing", {})
    carbon_section = sim_raw.get("carbon", {})
    llm_section = llm_raw.get("llm", {})
    decision_section = llm_raw.get("decision", {})
    db_section = settings_raw.get("database", {})
    mcp_section = settings_raw.get("mcp", {})
    output_section = settings_raw.get("output", {})
    logging_section = settings_raw.get("logging", {})

    # Override with environment variables where applicable
    sim_mode = os.getenv("SIMULATION_MODE", sim_section.get("mode", "energyplus"))
    ep_dir = os.getenv("ENERGYPLUS_DIR", sim_section.get("energyplus_dir", ""))
    llm_model = os.getenv("LLM_MODEL", llm_section.get("model", "llama3"))
    ollama_url = os.getenv("OLLAMA_BASE_URL", llm_section.get("base_url", "http://localhost:11434"))
    db_path = os.getenv("DATABASE_PATH", db_section.get("path", "data/eco_loop.db"))

    hvac = HVACConstraints(
        cooling_setpoint_min=hvac_section.get("cooling_setpoint", {}).get("min", 18.0),
        cooling_setpoint_max=hvac_section.get("cooling_setpoint", {}).get("max", 28.0),
        cooling_setpoint_default=hvac_section.get("cooling_setpoint", {}).get("default", 24.0),
        heating_setpoint_min=hvac_section.get("heating_setpoint", {}).get("min", 15.0),
        heating_setpoint_max=hvac_section.get("heating_setpoint", {}).get("max", 28.0),
        heating_setpoint_default=hvac_section.get("heating_setpoint", {}).get("default", 20.0),
        fan_speed_min=hvac_section.get("fan_speed", {}).get("min", 0.0),
        fan_speed_max=hvac_section.get("fan_speed", {}).get("max", 1.0),
        fan_speed_default=hvac_section.get("fan_speed", {}).get("default", 0.7),
        airflow_min=hvac_section.get("airflow", {}).get("min", 0.0),
        airflow_max=hvac_section.get("airflow", {}).get("max", 10.0),
        airflow_default=hvac_section.get("airflow", {}).get("default", 0.5),
    )

    comfort = (
        ComfortConstraints(
            **{
                k: comfort_section[k]
                for k in comfort_section
                if k in ComfortConstraints.model_fields
            }
        )
        if comfort_section
        else ComfortConstraints()
    )

    simulation = SimulationConfig(
        mode=sim_mode,
        timesteps_per_hour=sim_section.get("timesteps_per_hour", 4),
        total_hours=sim_section.get("total_hours", 168),
        idf_file=sim_section.get("idf_file", "data/idf/SmallOffice.idf"),
        epw_file=sim_section.get("epw_file", ""),
        energyplus_dir=ep_dir,
        hvac=hvac,
        comfort=comfort,
    )

    llm = LLMConfig(
        provider=llm_section.get("provider", "ollama"),
        base_url=ollama_url,
        model=llm_model,
        temperature=llm_section.get("temperature", 0.2),
        top_p=llm_section.get("top_p", 0.9),
        max_tokens=llm_section.get("max_tokens", 1024),
        timeout=llm_section.get("timeout", 120),
        max_attempts=llm_section.get("retry", {}).get("max_attempts", 3),
        wait_seconds=llm_section.get("retry", {}).get("wait_seconds", 2.0),
        query_every_n_steps=decision_section.get("query_every_n_steps", 4),
        always_reason=decision_section.get("always_reason", False),
        temp_drift_threshold=decision_section.get("temp_drift_threshold", 0.5),
        memory_size=decision_section.get("memory_size", 20),
    )

    pricing = PricingConfig(
        off_peak=pricing_section.get("off_peak", 0.08),
        mid_peak=pricing_section.get("mid_peak", 0.14),
        on_peak=pricing_section.get("on_peak", 0.22),
        peak_hours=pricing_section.get("peak_hours", [9, 10, 11, 17, 18, 19]),
        mid_peak_hours=pricing_section.get("mid_peak_hours", [7, 8, 12, 13, 14, 15, 16]),
    )

    carbon = CarbonConfig(
        intensity_g_per_kwh=carbon_section.get("intensity_g_per_kwh", 386.0),
        realtime_enabled=carbon_section.get("realtime_enabled", False),
    )

    return AppConfig(
        simulation=simulation,
        llm=llm,
        database=DatabaseConfig(path=db_path),
        mcp=MCPConfig(
            host=mcp_section.get("host", "127.0.0.1"),
            port=mcp_section.get("port", 8765),
            transport=mcp_section.get("transport", "stdio"),
        ),
        output=OutputConfig(
            **{k: output_section[k] for k in output_section if k in OutputConfig.model_fields}
        )
        if output_section
        else OutputConfig(),
        logging=LoggingConfig(
            level=os.getenv("LOG_LEVEL", logging_section.get("level", "INFO")),
            file=os.getenv("LOG_FILE", logging_section.get("file", "outputs/eco_loop.log")),
        ),
        pricing=pricing,
        carbon=carbon,
    )
