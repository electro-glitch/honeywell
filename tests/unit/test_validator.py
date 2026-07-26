"""Unit tests for ControlValidator."""

from __future__ import annotations

from app.controllers.validator import ControlValidator


class TestControlValidator:
    def setup_method(self):
        self.v = ControlValidator()

    # ── Basic validation ──────────────────────────────────────────────────────

    def test_valid_decision_passes(self):
        data = {
            "cooling_setpoint": 24.0,
            "heating_setpoint": 20.0,
            "fan_speed": 0.7,
            "airflow_m3s": 0.5,
        }
        result, notes = self.v.validate_and_clamp(data)
        assert result["cooling_setpoint"] == 24.0
        assert result["heating_setpoint"] == 20.0
        assert notes == ""

    # ── Clamping ─────────────────────────────────────────────────────────────

    def test_cooling_below_min_clamped(self):
        data = {"cooling_setpoint": 15.0, "heating_setpoint": 20.0, "fan_speed": 0.7}
        result, notes = self.v.validate_and_clamp(data)
        assert result["cooling_setpoint"] >= 18.0
        assert "cooling_setpoint" in notes

    def test_cooling_above_max_clamped(self):
        data = {"cooling_setpoint": 35.0, "heating_setpoint": 20.0, "fan_speed": 0.7}
        result, notes = self.v.validate_and_clamp(data)
        assert result["cooling_setpoint"] <= 28.0
        assert "cooling_setpoint" in notes

    def test_heating_above_max_clamped(self):
        data = {"cooling_setpoint": 24.0, "heating_setpoint": 30.0, "fan_speed": 0.7}
        result, notes = self.v.validate_and_clamp(data)
        assert result["heating_setpoint"] <= 28.0

    def test_fan_speed_above_1_clamped(self):
        data = {"cooling_setpoint": 24.0, "heating_setpoint": 20.0, "fan_speed": 1.5}
        result, notes = self.v.validate_and_clamp(data)
        assert result["fan_speed"] == 1.0
        assert "fan_speed" in notes

    def test_negative_fan_speed_clamped(self):
        data = {"cooling_setpoint": 24.0, "heating_setpoint": 20.0, "fan_speed": -0.5}
        result, notes = self.v.validate_and_clamp(data)
        assert result["fan_speed"] == 0.0

    def test_negative_airflow_clamped(self):
        data = {
            "cooling_setpoint": 24.0,
            "heating_setpoint": 20.0,
            "fan_speed": 0.7,
            "airflow_m3s": -1.0,
        }
        result, notes = self.v.validate_and_clamp(data)
        assert result["airflow_m3s"] == 0.0
        assert "airflow" in notes

    # ── Dead band ─────────────────────────────────────────────────────────────

    def test_dead_band_violation_corrected(self):
        """Cooling setpoint < heating + 2°C should be adjusted."""
        data = {"cooling_setpoint": 21.0, "heating_setpoint": 20.0, "fan_speed": 0.7}
        result, notes = self.v.validate_and_clamp(data)
        assert result["cooling_setpoint"] >= result["heating_setpoint"] + 2.0
        assert "Dead band" in notes

    def test_equal_setpoints_corrected(self):
        data = {"cooling_setpoint": 22.0, "heating_setpoint": 22.0, "fan_speed": 0.7}
        result, notes = self.v.validate_and_clamp(data)
        assert result["cooling_setpoint"] > result["heating_setpoint"]

    # ── is_safe ───────────────────────────────────────────────────────────────

    def test_is_safe_valid(self):
        data = {"cooling_setpoint": 24.0, "heating_setpoint": 20.0, "fan_speed": 0.7}
        safe, violations = self.v.is_safe(data)
        assert safe is True
        assert violations == []

    def test_is_safe_invalid(self):
        data = {"cooling_setpoint": 10.0, "heating_setpoint": 20.0, "fan_speed": 0.7}
        safe, violations = self.v.is_safe(data)
        assert safe is False
        assert len(violations) > 0

    # ── Missing fields ────────────────────────────────────────────────────────

    def test_missing_fields_use_defaults(self):
        result, notes = self.v.validate_and_clamp({})
        assert "cooling_setpoint" in result
        assert "heating_setpoint" in result
        assert "fan_speed" in result
