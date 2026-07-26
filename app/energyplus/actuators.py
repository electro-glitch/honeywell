"""
EnergyPlus Actuators Module
=============================
High-level functions for injecting control signals into the simulation.
Wraps the BaseSimulation setter methods with logging and bounds checking.
"""

from __future__ import annotations

from loguru import logger

from app.energyplus.wrapper import BaseSimulation


class ActuatorController:
    """
    Stateful controller that applies validated control commands
    to a running simulation instance.
    """

    def __init__(self, simulation: BaseSimulation) -> None:
        self._sim = simulation

    def apply_setpoints(
        self,
        cooling_setpoint: float,
        heating_setpoint: float,
        fan_speed: float,
        airflow_m3s: float | None = None,
    ) -> None:
        """
        Apply a full set of HVAC control commands.
        Values are assumed pre-validated by the ControlValidator.
        """
        logger.debug(
            f"Applying actuators — cooling: {cooling_setpoint}°C, "
            f"heating: {heating_setpoint}°C, fan: {fan_speed:.2f}, "
            f"airflow: {airflow_m3s}"
        )

        self._sim.set_cooling_setpoint(cooling_setpoint)
        self._sim.set_heating_setpoint(heating_setpoint)
        self._sim.set_fan_speed(fan_speed)

        if airflow_m3s is not None:
            self._sim.set_airflow(airflow_m3s)

    def set_cooling_setpoint(self, value_c: float) -> None:
        """Set cooling setpoint (°C)."""
        logger.debug(f"Cooling setpoint → {value_c}°C")
        self._sim.set_cooling_setpoint(value_c)

    def set_heating_setpoint(self, value_c: float) -> None:
        """Set heating setpoint (°C)."""
        logger.debug(f"Heating setpoint → {value_c}°C")
        self._sim.set_heating_setpoint(value_c)

    def set_fan_speed(self, fraction: float) -> None:
        """Set fan speed fraction (0–1)."""
        logger.debug(f"Fan speed → {fraction:.2f}")
        self._sim.set_fan_speed(fraction)

    def set_airflow(self, m3s: float) -> None:
        """Set airflow rate (m³/s)."""
        logger.debug(f"Airflow → {m3s} m³/s")
        self._sim.set_airflow(m3s)

    def reset_to_defaults(self) -> None:
        """Reset all actuators to safe default values."""
        from app.config import get_config

        cfg = get_config().simulation.hvac
        self._sim.set_cooling_setpoint(cfg.cooling_setpoint_default)
        self._sim.set_heating_setpoint(cfg.heating_setpoint_default)
        self._sim.set_fan_speed(cfg.fan_speed_default)
        self._sim.set_airflow(cfg.airflow_default)
        logger.info("All actuators reset to defaults")
