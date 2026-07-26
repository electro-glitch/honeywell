"""
EnergyPlus Simulation Wrapper
==============================
Provides a unified interface for both real EnergyPlus simulations
(via pyenergyplus) and the built-in synthetic mock simulation.

The wrapper auto-detects availability of EnergyPlus and falls back
to the mock implementation gracefully.
"""

from __future__ import annotations

import sys
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from app.config import get_config, SimulationConfig


class SimulationState:
    """Mutable simulation state passed through callbacks."""

    def __init__(self) -> None:
        self.timestep: int = 0
        self.is_running: bool = False
        self.should_stop: bool = False
        self.cooling_setpoint: float = 24.0
        self.heating_setpoint: float = 20.0
        self.fan_speed: float = 0.7
        self.airflow_m3s: float = 0.5
        self.api_data: dict = {}


class BaseSimulation(ABC):
    """Abstract base class for simulation backends."""

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config
        self.state = SimulationState()
        self._timestep_callbacks: list[Callable[[SimulationState], None]] = []

    def register_timestep_callback(self, fn: Callable[[SimulationState], None]) -> None:
        """Register a function to be called at each simulation timestep."""
        self._timestep_callbacks.append(fn)

    def _fire_callbacks(self) -> None:
        for fn in self._timestep_callbacks:
            try:
                fn(self.state)
            except Exception as e:
                logger.error(f"Timestep callback error: {e}")

    @abstractmethod
    def run_simulation(self, simulation_id: str) -> None:
        """Run the full simulation (blocking)."""
        ...

    @abstractmethod
    def stop_simulation(self) -> None:
        """Signal the simulation to stop."""
        ...

    @abstractmethod
    def get_zone_temperature(self) -> float:
        """Return current zone air temperature (°C)."""
        ...

    @abstractmethod
    def get_outdoor_temperature(self) -> float:
        """Return current outdoor temperature (°C)."""
        ...

    @abstractmethod
    def get_hvac_power(self) -> float:
        """Return current HVAC power (kW)."""
        ...

    @abstractmethod
    def get_humidity(self) -> float:
        """Return relative humidity (%)."""
        ...

    @abstractmethod
    def get_co2_ppm(self) -> float:
        """Return CO₂ concentration (ppm)."""
        ...

    @abstractmethod
    def get_occupancy_fraction(self) -> float:
        """Return occupancy as fraction of maximum (0–1)."""
        ...

    @abstractmethod
    def set_cooling_setpoint(self, value_c: float) -> None:
        """Set cooling setpoint (°C)."""
        ...

    @abstractmethod
    def set_heating_setpoint(self, value_c: float) -> None:
        """Set heating setpoint (°C)."""
        ...

    @abstractmethod
    def set_airflow(self, value_m3s: float) -> None:
        """Set zone airflow rate (m³/s)."""
        ...

    @abstractmethod
    def set_fan_speed(self, fraction: float) -> None:
        """Set fan speed fraction (0–1)."""
        ...


# ── Real EnergyPlus Wrapper ──────────────────────────────────────────────────

class EnergyPlusWrapper(BaseSimulation):
    """
    Wraps the EnergyPlus Python API (pyenergyplus).

    Requires EnergyPlus >= 9.6 to be installed and ENERGYPLUS_DIR set.
    """

    def __init__(self, config: SimulationConfig) -> None:
        super().__init__(config)
        self._api = None
        self._state_mgr = None
        self._handles: dict[str, int] = {}
        self._ep_state = None
        self._idf_path = Path(config.idf_file)
        self._epw_path = Path(config.epw_file) if config.epw_file else None
        self._ep_dir = Path(config.energyplus_dir)
        self._zones: list[str] = self._extract_zones()
        if not self._load_api():
            raise RuntimeError("EnergyPlus Python API is not available.")

    def _extract_zones(self) -> list[str]:
        """Parse IDF to extract zone names from Thermostat objects."""
        zones = []
        try:
            with open(self._idf_path, 'r', encoding='utf-8') as f:
                content = f.read()
            import re
            matches = re.finditer(r'ZoneControl:Thermostat,\s*([^,\r\n]+) Thermostat\b', content, re.IGNORECASE)
            for m in matches:
                z = m.group(1).strip()
                if z not in zones:
                    zones.append(z)
            if not zones:
                # Fallback: parse Zone, objects but skip plenums (no thermostats)
                matches = re.finditer(r'^\s*Zone,\s*([^,\r\n]+),', content, re.MULTILINE | re.IGNORECASE)
                for m in matches:
                    z = m.group(1).strip()
                    if z not in zones and "plenum" not in z.lower():
                        zones.append(z)
        except Exception as e:
            logger.warning(f"Failed to parse zones from IDF: {e}")
            
        if not zones:
            zones = ["Zone 1"]
        return zones

    def _load_api(self) -> bool:
        """Attempt to load EnergyPlus Python API."""
        try:
            ep_dir = str(self._ep_dir)
            import sys
            if ep_dir not in sys.path:
                sys.path.insert(0, ep_dir)
            from pyenergyplus.api import EnergyPlusAPI  # type: ignore[import]
            self._api = EnergyPlusAPI()
            logger.info("EnergyPlus Python API loaded successfully")
            return True
        except ImportError:
            logger.warning(
                "pyenergyplus not found. Falling back to mock simulation. "
                f"Ensure EnergyPlus is installed at {self._ep_dir}"
            )
            return False

    def run_simulation(self, simulation_id: str) -> None:
        if not self._load_api():
            raise RuntimeError("EnergyPlus API unavailable")

        self._ep_state = self._api.state_manager.new_state()
        api = self._api

        # Register callbacks
        api.runtime.callback_begin_zone_timestep_after_init_heat_balance(
            self._ep_state, self._on_timestep
        )

        self.state.is_running = True

        out_dir = Path("outputs") / simulation_id
        out_dir.mkdir(parents=True, exist_ok=True)

        for zone in self._zones:
            api.exchange.request_variable(self._ep_state, "Zone Mean Air Temperature", zone)
            api.exchange.request_variable(self._ep_state, "Zone Air Relative Humidity", zone)
            api.exchange.request_variable(self._ep_state, "Zone Air CO2 Concentration", zone)
        api.exchange.request_variable(self._ep_state, "Facility Total HVAC Electricity Demand Rate", "Whole Building")
        api.exchange.request_variable(self._ep_state, "Zone Mechanical Ventilation Mass Flow Rate", "Whole Building")

        # Build argument list
        args = [
            "-w", str(self._epw_path.resolve()) if self._epw_path else "",
            "-d", str(out_dir.resolve()),
            str(self._idf_path.resolve()),
        ]

        logger.info("Starting EnergyPlus simulation with args: " + " ".join(args))
        logger.info(f"Controlling zones: {self._zones}")
        
        exit_code = api.runtime.run_energyplus(self._ep_state, args)
        self.state.is_running = False

        if exit_code != 0:
            raise RuntimeError(f"EnergyPlus exited with code {exit_code}")

    def _on_timestep(self, ep_state) -> None:
        """EnergyPlus timestep callback fires once per simulation timestep."""
        if self.state.should_stop:
            self._api.runtime.stop_simulation(ep_state)
            return

        self.state.timestep += 1
        self.state.api_data["ep_state"] = ep_state
        self._fire_callbacks()

        # Apply pending setpoint changes
        self._apply_actuators(ep_state)

    def _apply_actuators(self, ep_state) -> None:
        try:
            if self.state.cooling_setpoint is not None and self.state.heating_setpoint is not None:
                for zone in self._zones:
                    c_key = f"cool_sp_{zone}"
                    h_key = f"heat_sp_{zone}"
                    
                    c_handle = self._handles.get(c_key, -1)
                    h_handle = self._handles.get(h_key, -1)
                    
                    if c_handle < 0:
                        c_handle = self._api.exchange.get_actuator_handle(
                            ep_state, "Zone Temperature Control", "Cooling Setpoint", zone
                        )
                        if c_handle >= 0:
                            self._handles[c_key] = c_handle
                            
                    if h_handle < 0:
                        h_handle = self._api.exchange.get_actuator_handle(
                            ep_state, "Zone Temperature Control", "Heating Setpoint", zone
                        )
                        if h_handle >= 0:
                            self._handles[h_key] = h_handle
                    
                    if c_handle >= 0:
                        self._api.exchange.set_actuator_value(ep_state, c_handle, self.state.cooling_setpoint)
                    if h_handle >= 0:
                        self._api.exchange.set_actuator_value(ep_state, h_handle, self.state.heating_setpoint)
        except Exception as e:
            logger.debug(f"Actuator application skipped: {e}")

    def stop_simulation(self) -> None:
        self.state.should_stop = True

    def _get_variable_avg(self, ep_state, var_name: str, fallback: float) -> float:
        total = 0.0
        count = 0
        for zone in self._zones:
            key = f"{var_name}_{zone}"
            handle = self._handles.get(key, -1)
            if handle < 0:
                handle = self._api.exchange.get_variable_handle(ep_state, var_name, zone)
                if handle >= 0:
                    self._handles[key] = handle
                    
            if handle >= 0:
                total += self._api.exchange.get_variable_value(ep_state, handle)
                count += 1
        return total / count if count > 0 else fallback

    def get_zone_temperature(self) -> float:
        ep_state = self.state.api_data.get("ep_state")
        if ep_state is None:
            return self.state.cooling_setpoint - 1.0
        return self._get_variable_avg(ep_state, "Zone Mean Air Temperature", 22.0)

    def get_outdoor_temperature(self) -> float:
        ep_state = self.state.api_data.get("ep_state")
        if ep_state is None:
            return 15.0
        try:
            if "outdoor_temp" not in self._handles:
                self._handles["outdoor_temp"] = self._api.exchange.get_variable_handle(
                    ep_state, "Site Outdoor Air Drybulb Temperature", "Environment"
                )
            handle = self._handles["outdoor_temp"]
            if handle >= 0:
                return self._api.exchange.get_variable_value(ep_state, handle)
        except Exception:
            pass
        return 15.0

    def get_hvac_power(self) -> float:
        ep_state = self.state.api_data.get("ep_state")
        if not ep_state:
            return 0.0

        try:
            handle = self._handles.get("hvac_power", -1)
            if handle < 0:
                handle = self._api.exchange.get_variable_handle(
                    ep_state, "Facility Total HVAC Electricity Demand Rate", "Whole Building"
                )
                if handle >= 0:
                    self._handles["hvac_power"] = handle
                    
            if handle >= 0:
                return self._api.exchange.get_variable_value(ep_state, handle) / 1000.0
        except Exception:
            pass
            
        avg_flow = self._get_variable_avg(ep_state, "Zone Mechanical Ventilation Mass Flow Rate", 0.0)
        return avg_flow * 1.5 * len(self._zones)

    def get_humidity(self) -> float:
        ep_state = self.state.api_data.get("ep_state")
        if ep_state is None:
            return 50.0
        return self._get_variable_avg(ep_state, "Zone Air Relative Humidity", 50.0)

    def get_co2_ppm(self) -> float:
        ep_state = self.state.api_data.get("ep_state")
        if ep_state is None:
            return 400.0
        return self._get_variable_avg(ep_state, "Zone Air CO2 Concentration", 400.0)

    def get_occupancy_fraction(self) -> float:
        ep_state = self.state.api_data.get("ep_state")
        if ep_state is None:
            return 0.0
        avg_occ = self._get_variable_avg(ep_state, "Zone People Occupant Count", 0.0)
        return min(1.0, avg_occ / 5.0)

    def set_cooling_setpoint(self, value_c: float) -> None:
        self.state.cooling_setpoint = value_c

    def set_heating_setpoint(self, value_c: float) -> None:
        self.state.heating_setpoint = value_c

    def set_airflow(self, value_m3s: float) -> None:
        self.state.airflow_m3s = value_m3s

    def set_fan_speed(self, fraction: float) -> None:
        self.state.fan_speed = fraction

# ── Mock Simulation (no EnergyPlus required) ─────────────────────────────────

class MockSimulation(BaseSimulation):
    """
    Synthetic building simulation for development/demo without EnergyPlus.

    Uses simple physics-inspired equations to produce realistic-looking
    building performance data.
    """

    def __init__(self, config: SimulationConfig) -> None:
        super().__init__(config)
        self._indoor_temp = 22.0
        self._outdoor_temp = 15.0
        self._humidity = 50.0
        self._co2 = 450.0
        self._hvac_power_kw = 5.0
        self._hour: int = 0  # hour of day (0–23)

    # ── Simulation loop ──────────────────────────────────────────────────────

    def run_simulation(self, simulation_id: str) -> None:
        self.state.is_running = True
        total_steps = self.config.total_hours * self.config.timesteps_per_hour
        dt_hours = 1.0 / self.config.timesteps_per_hour

        logger.info(
            f"[Mock] Starting simulation {simulation_id} "
            f"— {total_steps} timesteps ({self.config.total_hours}h)"
        )

        for step in range(total_steps):
            if self.state.should_stop:
                logger.info("[Mock] Simulation stopped by request.")
                break

            self.state.timestep = step
            self._hour = int((step * dt_hours) % 24)

            # Advance synthetic physics
            self._advance_physics(dt_hours)

            # Fire registered callbacks (metrics collection, LLM loop, etc.)
            self._fire_callbacks()

            # Small sleep to avoid CPU spin (remove for max speed)
            # time.sleep(0.001)

        self.state.is_running = False
        logger.info(f"[Mock] Simulation {simulation_id} finished at step {self.state.timestep}")

    def _advance_physics(self, dt_hours: float) -> None:
        """Update synthetic building state for one timestep."""
        import math
        import random

        h = self._hour
        step = self.state.timestep

        # Outdoor temperature: clean sinusoidal daily cycle, peak at 14:00
        # Slow weekly variation (±3°C) to add realism
        day = step * dt_hours / 24.0
        seasonal_drift = 2.0 * math.sin(2 * math.pi * day / 7.0)
        self._outdoor_temp = (
            16.0                                              # mean outdoor temp
            + seasonal_drift                                  # weekly variation
            + 8.0 * math.sin(math.pi * (h - 6) / 12.0)      # daily cycle peak at 14:00
        )

        # Occupancy-driven heat gains
        occ = self.get_occupancy_fraction()
        solar_gain = max(0.0, 3.0 * math.sin(math.pi * (h - 6) / 12.0))
        occupancy_gain = occ * 1.2   # internal heat from people (kW equiv)
        equipment_gain = occ * 0.6   # equipment loads

        # HVAC control — stronger authority so thermostat is effective
        cool_sp = self.state.cooling_setpoint
        heat_sp = self.state.heating_setpoint

        if self._indoor_temp > cool_sp:
            hvac_effect = -4.0 * (self._indoor_temp - cool_sp) * max(self.state.fan_speed, 0.5)
        elif self._indoor_temp < heat_sp:
            hvac_effect = +4.0 * (heat_sp - self._indoor_temp) * max(self.state.fan_speed, 0.5)
        else:
            hvac_effect = 0.0

        # Thermal envelope: indoor drifts toward outdoor (conductance)
        envelope_drift = (self._outdoor_temp - self._indoor_temp) * 0.06 * dt_hours

        # Update indoor temperature
        d_temp = (
            envelope_drift
            + solar_gain * 0.08 * dt_hours
            + occupancy_gain * 0.04 * dt_hours
            + hvac_effect * dt_hours
            + random.gauss(0, 0.03)
        )
        self._indoor_temp = max(12.0, min(40.0, self._indoor_temp + d_temp))

        # HVAC power: proportional to control effort
        self._hvac_power_kw = abs(hvac_effect) * 2.5 + occ * 1.5 + 0.5

        # Humidity: increases with occupancy, reduced by HVAC
        target_humidity = 35.0 + occ * 25.0 + max(0.0, self._outdoor_temp - 18) * 0.4
        self._humidity += (target_humidity - self._humidity) * 0.05 * dt_hours
        self._humidity = max(20.0, min(90.0, self._humidity))

        # CO2: rises with occupancy, reduced by ventilation
        target_co2 = 420.0 + occ * 550.0
        self._co2 += (target_co2 - self._co2) * 0.12 * dt_hours * (1.0 + self.state.airflow_m3s)
        self._co2 = max(400.0, min(2000.0, self._co2))

    def stop_simulation(self) -> None:
        self.state.should_stop = True

    # ── Getters ──────────────────────────────────────────────────────────────

    def get_zone_temperature(self) -> float:
        return round(self._indoor_temp, 2)

    def get_outdoor_temperature(self) -> float:
        return round(self._outdoor_temp, 2)

    def get_hvac_power(self) -> float:
        return round(self._hvac_power_kw, 3)

    def get_humidity(self) -> float:
        return round(self._humidity, 1)

    def get_co2_ppm(self) -> float:
        return round(self._co2, 1)

    def get_occupancy_fraction(self) -> float:
        """Read occupancy from schedule based on hour of day."""
        # Use hardcoded schedule approximation
        h = self._hour
        schedule = {
            0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.05,
            6: 0.1, 7: 0.5, 8: 0.9, 9: 1.0, 10: 1.0, 11: 1.0,
            12: 0.7, 13: 0.9, 14: 1.0, 15: 1.0, 16: 0.8, 17: 0.5,
            18: 0.2, 19: 0.1, 20: 0.05, 21: 0.0, 22: 0.0, 23: 0.0,
        }
        return schedule.get(h, 0.0)

    # ── Setters ──────────────────────────────────────────────────────────────

    def set_cooling_setpoint(self, value_c: float) -> None:
        self.state.cooling_setpoint = value_c

    def set_heating_setpoint(self, value_c: float) -> None:
        self.state.heating_setpoint = value_c

    def set_airflow(self, value_m3s: float) -> None:
        self.state.airflow_m3s = value_m3s

    def set_fan_speed(self, fraction: float) -> None:
        self.state.fan_speed = fraction


# ── Factory ───────────────────────────────────────────────────────────────────

def create_simulation(config: Optional[SimulationConfig] = None) -> BaseSimulation:
    """
    Factory function.  Returns the appropriate simulation backend based on config.

    - "energyplus" → tries EnergyPlusWrapper, falls back to Mock on failure
    - "mock"       → always returns MockSimulation
    """
    if config is None:
        config = get_config().simulation

    if config.mode == "energyplus":
        try:
            ep = EnergyPlusWrapper(config)
            logger.info("Using real EnergyPlus simulation backend")
            return ep
        except Exception as exc:
            logger.warning(f"EnergyPlus backend failed ({exc}); using mock")

    logger.info("Using mock simulation backend")
    return MockSimulation(config)
