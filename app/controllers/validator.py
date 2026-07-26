"""
Control Validator
==================
Validates and clamps LLM-generated control decisions against
hard safety constraints before applying them to the simulation.

Rules:
  - Cooling setpoint: 18°C – 28°C
  - Heating setpoint: 15°C – 28°C
  - Fan speed: 0.0 – 1.0
  - Airflow: 0.0 – 10.0 m³/s
  - Cooling setpoint must be ≥ heating setpoint + 2°C (dead band)
  - Fan speed must be ≥ 0.1 during occupied hours (min ventilation)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.config import HVACConstraints, get_config


@dataclass
class ValidationResult:
    is_valid: bool
    clamped: bool
    notes: list[str]


class ControlValidator:
    """
    Validates and sanitizes control decisions.

    Enforces hard constraints and logs all violations.
    """

    # Hard absolute limits (failsafe)
    ABS_COOL_MIN = 15.0
    ABS_COOL_MAX = 32.0
    ABS_HEAT_MIN = 10.0
    ABS_HEAT_MAX = 30.0
    ABS_FAN_MIN = 0.0
    ABS_FAN_MAX = 1.0
    ABS_AIRFLOW_MIN = 0.0
    ABS_AIRFLOW_MAX = 15.0
    MIN_DEADBAND = 2.0  # cooling must be at least 2°C above heating

    def __init__(self, constraints: Optional[HVACConstraints] = None) -> None:
        self._c = constraints or get_config().simulation.hvac

    def validate_and_clamp(self, data: dict) -> tuple[dict, str]:
        """
        Validate and clamp a control decision dict.

        Returns:
            (clamped_data, notes_string)
        """
        notes: list[str] = []
        result = dict(data)

        # ── Cooling Setpoint ─────────────────────────────────────────────────
        cool = float(result.get("cooling_setpoint", self._c.cooling_setpoint_default))
        if cool < self._c.cooling_setpoint_min:
            notes.append(f"cooling_setpoint {cool}°C below min {self._c.cooling_setpoint_min}°C")
            cool = self._c.cooling_setpoint_min
        if cool > self._c.cooling_setpoint_max:
            notes.append(f"cooling_setpoint {cool}°C above max {self._c.cooling_setpoint_max}°C")
            cool = self._c.cooling_setpoint_max

        # ── Heating Setpoint ─────────────────────────────────────────────────
        heat = float(result.get("heating_setpoint", self._c.heating_setpoint_default))
        if heat < self._c.heating_setpoint_min:
            notes.append(f"heating_setpoint {heat}°C below min {self._c.heating_setpoint_min}°C")
            heat = self._c.heating_setpoint_min
        if heat > self._c.heating_setpoint_max:
            notes.append(f"heating_setpoint {heat}°C above max {self._c.heating_setpoint_max}°C")
            heat = self._c.heating_setpoint_max

        # ── Dead Band Enforcement ────────────────────────────────────────────
        if cool < heat + self.MIN_DEADBAND:
            notes.append(
                f"Dead band violation: cool={cool} < heat={heat}+{self.MIN_DEADBAND}. "
                f"Adjusting cooling to {heat + self.MIN_DEADBAND}°C"
            )
            cool = heat + self.MIN_DEADBAND

        # ── Fan Speed ────────────────────────────────────────────────────────
        fan = float(result.get("fan_speed", self._c.fan_speed_default))
        if fan < self._c.fan_speed_min:
            notes.append(f"fan_speed {fan} below min {self._c.fan_speed_min}")
            fan = self._c.fan_speed_min
        if fan > self._c.fan_speed_max:
            notes.append(f"fan_speed {fan} above max {self._c.fan_speed_max}")
            fan = self._c.fan_speed_max

        # ── Airflow ──────────────────────────────────────────────────────────
        airflow = result.get("airflow_m3s")
        if airflow is not None:
            airflow = float(airflow)
            if airflow < self._c.airflow_min:
                notes.append(f"airflow {airflow} m³/s below min {self._c.airflow_min}")
                airflow = self._c.airflow_min
            if airflow > self._c.airflow_max:
                notes.append(f"airflow {airflow} m³/s above max {self._c.airflow_max}")
                airflow = self._c.airflow_max

        # ── Absolute Failsafe ────────────────────────────────────────────────
        cool = max(self.ABS_COOL_MIN, min(self.ABS_COOL_MAX, cool))
        heat = max(self.ABS_HEAT_MIN, min(self.ABS_HEAT_MAX, heat))
        fan = max(self.ABS_FAN_MIN, min(self.ABS_FAN_MAX, fan))

        if notes:
            logger.warning(f"Validation clamped decision: {'; '.join(notes)}")

        result["cooling_setpoint"] = round(cool, 1)
        result["heating_setpoint"] = round(heat, 1)
        result["fan_speed"] = round(fan, 2)
        if airflow is not None:
            result["airflow_m3s"] = round(airflow, 2)

        return result, "; ".join(notes)

    def is_safe(self, data: dict) -> tuple[bool, list[str]]:
        """
        Check if a decision is safe WITHOUT modifying it.
        Returns (is_safe, list_of_violations).
        """
        violations = []

        cool = float(data.get("cooling_setpoint", 24.0))
        heat = float(data.get("heating_setpoint", 20.0))
        fan = float(data.get("fan_speed", 0.7))

        if cool < self._c.cooling_setpoint_min:
            violations.append(f"cooling {cool}°C < min {self._c.cooling_setpoint_min}°C")
        if cool > self._c.cooling_setpoint_max:
            violations.append(f"cooling {cool}°C > max {self._c.cooling_setpoint_max}°C")
        if heat < self._c.heating_setpoint_min:
            violations.append(f"heating {heat}°C < min {self._c.heating_setpoint_min}°C")
        if heat > self._c.heating_setpoint_max:
            violations.append(f"heating {heat}°C > max {self._c.heating_setpoint_max}°C")
        if fan < 0.0 or fan > 1.0:
            violations.append(f"fan_speed {fan} outside [0, 1]")
        if cool < heat + self.MIN_DEADBAND:
            violations.append(f"dead band violation: cool-heat={cool-heat:.1f} < {self.MIN_DEADBAND}")

        return len(violations) == 0, violations
