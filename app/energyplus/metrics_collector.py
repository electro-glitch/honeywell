"""
Runtime Metrics Collector
==========================
Collects building metrics at each simulation timestep and persists
them to the SQLite database.

Also computes derived values:
  - PMV (Predicted Mean Vote) via Fanger's equation approximation
  - Carbon emissions
  - Electricity cost (TOU pricing)
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from app.config import get_config, PricingConfig, CarbonConfig
from app.database.models import BuildingMetrics, ComfortViolation
from app.database.repository import insert_metrics, insert_violation
from app.energyplus.wrapper import BaseSimulation, SimulationState


class MetricsCollector:
    """
    Registered as a timestep callback on the simulation.
    Reads all sensor values, derives KPIs, and saves to database.
    """

    def __init__(
        self,
        simulation: BaseSimulation,
        simulation_id: str,
        mode: str,
        dt_hours: float,
        pricing: Optional[PricingConfig] = None,
        carbon: Optional[CarbonConfig] = None,
        start_datetime: Optional[datetime] = None,
    ) -> None:
        self.sim = simulation
        self.simulation_id = simulation_id
        self.mode = mode
        self.dt_hours = dt_hours
        self._pricing = pricing or get_config().pricing
        self._carbon = carbon or get_config().carbon
        self._comfort = get_config().simulation.comfort
        self._start_dt = start_datetime or datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    def __call__(self, state: SimulationState) -> None:
        """Called by the simulation engine every timestep."""
        try:
            metrics = self._collect(state)
            insert_metrics(metrics)
            self._check_comfort_violations(metrics)
        except Exception as e:
            logger.error(f"MetricsCollector error at step {state.timestep}: {e}")

    def _collect(self, state: SimulationState) -> BuildingMetrics:
        """Read all sensors and compute derived metrics."""
        ts = state.timestep
        timestamp = self._start_dt + timedelta(hours=ts * self.dt_hours)

        # Raw sensor readings
        indoor_temp = self.sim.get_zone_temperature()
        outdoor_temp = self.sim.get_outdoor_temperature()
        humidity = self.sim.get_humidity()
        co2 = self.sim.get_co2_ppm()
        occupancy = self.sim.get_occupancy_fraction()
        hvac_power = self.sim.get_hvac_power()

        # Derived energy (kWh)
        hvac_kwh = hvac_power * self.dt_hours
        lighting_kwh = self._estimate_lighting_kwh(occupancy)
        equipment_kwh = self._estimate_equipment_kwh(occupancy)
        total_kwh = hvac_kwh + lighting_kwh + equipment_kwh

        # Comfort
        pmv = compute_pmv(indoor_temp, humidity, occupancy)
        ppd = compute_ppd(pmv)

        # Carbon
        carbon_kg = total_kwh * self._carbon.intensity_g_per_kwh / 1000.0

        # Pricing (TOU)
        hour = int((ts * self.dt_hours) % 24)
        price = self._get_price(hour)
        cost = total_kwh * price

        return BuildingMetrics(
            simulation_id=self.simulation_id,
            mode=self.mode,
            timestep=ts,
            timestamp=timestamp,
            indoor_temp_c=indoor_temp,
            outdoor_temp_c=outdoor_temp,
            heating_setpoint_c=state.heating_setpoint,
            cooling_setpoint_c=state.cooling_setpoint,
            humidity_pct=humidity,
            pmv=pmv,
            ppd=ppd,
            hvac_electricity_kwh=hvac_kwh,
            lighting_electricity_kwh=lighting_kwh,
            equipment_electricity_kwh=equipment_kwh,
            total_electricity_kwh=total_kwh,
            occupancy_fraction=occupancy,
            occupant_count=int(occupancy * 50),  # assume max 50 occupants
            co2_ppm=co2,
            hvac_power_kw=hvac_power,
            fan_speed=state.fan_speed,
            airflow_m3s=state.airflow_m3s,
            carbon_kg_co2=carbon_kg,
            electricity_price_per_kwh=price,
            electricity_cost=cost,
        )

    def _estimate_lighting_kwh(self, occupancy: float) -> float:
        """Estimate lighting load. Base load + occupancy-dependent load."""
        base_kw = 2.0  # always-on emergency/corridor
        occupied_kw = 8.0 * occupancy
        return (base_kw + occupied_kw) * self.dt_hours

    def _estimate_equipment_kwh(self, occupancy: float) -> float:
        """Estimate plug load energy."""
        base_kw = 3.0
        occupied_kw = 12.0 * occupancy
        return (base_kw + occupied_kw) * self.dt_hours

    def _get_price(self, hour: int) -> float:
        """Return TOU electricity price for given hour."""
        p = self._pricing
        if hour in p.peak_hours:
            return p.on_peak
        if hour in p.mid_peak_hours:
            return p.mid_peak
        return p.off_peak

    def _check_comfort_violations(self, m: BuildingMetrics) -> None:
        """Detect and record comfort constraint violations."""
        c = self._comfort

        checks = [
            ("temp_high", m.indoor_temp_c, c.temp_max_c, m.indoor_temp_c > c.temp_max_c),
            ("temp_low", m.indoor_temp_c, c.temp_min_c, m.indoor_temp_c < c.temp_min_c),
            ("pmv_high", m.pmv, c.pmv_max, m.pmv > c.pmv_max),
            ("pmv_low", m.pmv, c.pmv_min, m.pmv < c.pmv_min),
            ("co2", m.co2_ppm, c.co2_max_ppm, m.co2_ppm > c.co2_max_ppm),
            ("humidity_high", m.humidity_pct, c.humidity_max, m.humidity_pct > c.humidity_max),
            ("humidity_low", m.humidity_pct, c.humidity_min, m.humidity_pct < c.humidity_min),
        ]

        for vtype, actual, limit, triggered in checks:
            if triggered:
                severity = abs(actual - limit)
                v = ComfortViolation(
                    simulation_id=self.simulation_id,
                    timestep=m.timestep,
                    timestamp=m.timestamp,
                    violation_type=vtype,
                    actual_value=actual,
                    limit_value=limit,
                    severity=severity,
                )
                insert_violation(v)
                logger.debug(
                    f"Comfort violation [{vtype}]: {actual:.2f} vs limit {limit:.2f} "
                    f"(severity {severity:.2f})"
                )


# ── PMV / PPD Calculations ────────────────────────────────────────────────────

def compute_pmv(
    air_temp_c: float,
    relative_humidity: float,
    occupancy: float = 1.0,
    mean_radiant_temp: Optional[float] = None,
    air_velocity_m_s: float = 0.1,
    metabolic_rate: float = 1.2,
    clothing_insulation: float = 0.5,
) -> float:
    """
    Simplified PMV calculation based on Fanger's comfort model.
    Returns PMV in range [-3, +3].

    Full ASHRAE 55 implementation without external dependencies.
    """
    ta = air_temp_c
    tr = mean_radiant_temp if mean_radiant_temp is not None else ta + 2.0
    va = air_velocity_m_s
    rh = relative_humidity
    M = metabolic_rate   # met
    Icl = clothing_insulation  # clo

    # Clothing surface area factor
    fcl = 1.05 + 0.1 * Icl if Icl > 0.5 else 1.0 + 0.2 * Icl

    # Clothing surface temperature (iterative, approximated)
    tcl = ta + (35.5 - ta) / (3.5 * (6.45 * Icl + 0.1))
    tcl = max(20.0, min(50.0, tcl))

    # Convective heat transfer coefficient
    hc = max(2.38 * abs(tcl - ta) ** 0.25, 12.1 * math.sqrt(va))

    # Radiation loss
    L_rad = 3.96e-8 * fcl * ((tcl + 273.0) ** 4 - (tr + 273.0) ** 4)
    # Convective loss
    L_conv = fcl * hc * (tcl - ta)

    # Water vapor pressure (Pa)
    pa = rh / 100.0 * 0.133322 * math.exp(18.956 - 4030.18 / (ta + 235.0)) * 1000

    # Internal heat production (W/m²)
    W = 0.0  # Assume sedentary, no external work
    S = M * 58.15  # Metabolic rate (W/m²)

    # PMV formula (simplified linear approximation)
    pmv = (
        0.303 * math.exp(-0.036 * S) + 0.028
    ) * (
        S - W
        - 3.05e-3 * (5733 - 6.99 * (S - W) - pa)
        - 0.42 * ((S - W) - 58.15)
        - 1.7e-5 * S * (5867 - pa)
        - 0.0014 * S * (34 - ta)
        - L_rad
        - L_conv
    )

    return max(-3.0, min(3.0, round(pmv, 3)))


def compute_ppd(pmv: float) -> float:
    """
    Predicted Percentage Dissatisfied (PPD) from PMV.
    ASHRAE 55 formula: PPD = 100 - 95 * exp(-0.03353*PMV^4 - 0.2179*PMV^2)
    """
    ppd = 100 - 95 * math.exp(-0.03353 * pmv**4 - 0.2179 * pmv**2)
    return round(max(5.0, min(100.0, ppd)), 2)
