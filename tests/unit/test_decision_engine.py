"""Unit tests for the decision engine and LLM client."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.agent.llm_client import LLMError, StubLLMClient, extract_json
from app.agent.memory import DecisionMemory
from app.agent.prompts import SYSTEM_PROMPT, build_decision_prompt
from app.database.models import ControlDecision


class TestExtractJSON:
    def test_plain_json(self):
        text = (
            '{"cooling_setpoint": 24.0, "heating_setpoint": 20.0, "fan_speed": 0.7, "reason": "ok"}'
        )
        data = extract_json(text)
        assert data["cooling_setpoint"] == 24.0

    def test_json_in_markdown_block(self):
        text = '```json\n{"cooling_setpoint": 23.0, "heating_setpoint": 19.0, "fan_speed": 0.6, "reason": "test"}\n```'
        data = extract_json(text)
        assert data["cooling_setpoint"] == 23.0

    def test_json_with_surrounding_text(self):
        text = 'Based on analysis: {"cooling_setpoint": 25.0, "heating_setpoint": 21.0, "fan_speed": 0.5, "reason": "energy savings"} This makes sense.'
        data = extract_json(text)
        assert data["cooling_setpoint"] == 25.0

    def test_invalid_raises(self):
        with pytest.raises(LLMError):
            extract_json("No JSON here at all")

    def test_malformed_json_raises(self):
        with pytest.raises(LLMError):
            extract_json("{invalid json}")


class TestStubLLMClient:
    def setup_method(self):
        self.client = StubLLMClient()

    def test_high_pmv_reduces_cooling(self):
        prompt = (
            "Indoor Temperature: 26.0°C\nPMV (Comfort Index): 0.8\nOccupancy: 80%\nCO₂: 650 ppm"
        )
        response = self.client.generate(prompt)
        data = json.loads(response)
        # High PMV → cooling should be lower than default
        assert data["cooling_setpoint"] <= 24.0
        assert "fan_speed" in data

    def test_low_occupancy_setback(self):
        prompt = "Indoor Temperature: 23.0°C\nPMV (Comfort Index): 0.0\nOccupancy: 0%\nCO₂: 400 ppm"
        response = self.client.generate(prompt)
        data = json.loads(response)
        # Low occupancy → setback mode
        assert data["cooling_setpoint"] >= 25.0
        assert data["fan_speed"] <= 0.4

    def test_high_co2_increases_fan(self):
        prompt = (
            "Indoor Temperature: 23.0°C\nPMV (Comfort Index): 0.1\nOccupancy: 70%\nCO₂: 950 ppm"
        )
        response = self.client.generate(prompt)
        data = json.loads(response)
        # High CO₂ → fan speed should increase
        assert data["fan_speed"] >= 0.5

    def test_output_has_required_fields(self):
        response = self.client.generate(
            "Indoor Temperature: 22.0°C\nPMV (Comfort Index): 0.0\nOccupancy: 50%\nCO₂: 500 ppm"
        )
        data = json.loads(response)
        for field in ["cooling_setpoint", "heating_setpoint", "fan_speed", "reason"]:
            assert field in data


class TestDecisionMemory:
    def _make_decision(self, timestep: int, cool: float, heat: float) -> ControlDecision:
        return ControlDecision(
            simulation_id="test",
            timestep=timestep,
            timestamp=datetime.utcnow(),
            cooling_setpoint=cool,
            heating_setpoint=heat,
            fan_speed=0.7,
            reason="test",
        )

    def test_add_and_retrieve(self):
        memory = DecisionMemory(max_size=5)
        d = self._make_decision(0, 24.0, 20.0)
        memory.add(d)
        assert len(memory) == 1
        recent = memory.get_recent(1)
        assert recent[0].cooling_setpoint == 24.0

    def test_sliding_window(self):
        memory = DecisionMemory(max_size=3)
        for i in range(5):
            memory.add(self._make_decision(i, 22.0 + i, 18.0))
        assert len(memory) == 3
        # Should have the last 3
        recent = memory.get_recent(3)
        assert recent[-1].cooling_setpoint == 26.0  # last added (22+4)

    def test_oscillation_detection(self):
        memory = DecisionMemory(max_size=10)
        # Add alternating high/low setpoints
        for i in range(6):
            cool = 28.0 if i % 2 == 0 else 18.0
            memory.add(self._make_decision(i, cool, 16.0))
        assert memory.detect_oscillation(threshold=2.0) is True

    def test_no_oscillation_stable(self):
        memory = DecisionMemory(max_size=10)
        for i in range(6):
            memory.add(self._make_decision(i, 24.0 + i * 0.01, 20.0))
        assert memory.detect_oscillation(threshold=2.0) is False

    def test_get_recent_dicts(self):
        memory = DecisionMemory(max_size=5)
        for i in range(3):
            memory.add(self._make_decision(i, 24.0, 20.0))
        dicts = memory.get_recent_dicts(2)
        assert len(dicts) == 2
        assert all("reason" in d for d in dicts)

    def test_explanation_log(self):
        memory = DecisionMemory(max_size=5)
        memory.add(self._make_decision(0, 24.0, 20.0))
        log = memory.to_explanation_log()
        assert len(log) == 1
        assert "timestep" in log[0]
        assert "reason" in log[0]


class TestSystemPrompt:
    def test_prompt_contains_comfort_constraints(self):
        assert "PMV" in SYSTEM_PROMPT
        assert "22" in SYSTEM_PROMPT  # temp min
        assert "25" in SYSTEM_PROMPT  # temp max

    def test_decision_prompt_includes_metrics(self):
        metrics = {
            "indoor_temp_c": 24.0,
            "outdoor_temp_c": 15.0,
            "humidity_pct": 50.0,
            "pmv": 0.3,
            "ppd": 6.0,
            "co2_ppm": 600.0,
            "occupancy_fraction": 0.8,
            "cooling_setpoint_c": 24.0,
            "heating_setpoint_c": 20.0,
            "fan_speed": 0.7,
            "hvac_power_kw": 10.0,
            "total_electricity_kwh": 5.0,
            "hvac_electricity_kwh": 3.0,
            "electricity_cost": 0.7,
            "carbon_kg_co2": 1.9,
        }
        prompt = build_decision_prompt(metrics)
        assert "24.0" in prompt
        assert "PMV" in prompt
        assert "0.8" in prompt or "80%" in prompt
