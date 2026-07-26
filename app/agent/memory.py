"""
Decision Memory
================
Stores and retrieves recent control decisions for LLM context.
Implements a sliding window of recent decisions with analysis.
"""

from __future__ import annotations

from collections import deque

from app.database.models import ControlDecision


class DecisionMemory:
    """
    In-memory sliding window of recent control decisions.
    Provides context to the LLM for trend-aware reasoning.
    """

    def __init__(self, max_size: int = 20) -> None:
        self._decisions: deque[ControlDecision] = deque(maxlen=max_size)
        self._max_size = max_size

    def add(self, decision: ControlDecision) -> None:
        """Add a new decision to memory."""
        self._decisions.append(decision)

    def get_recent(self, n: int = 5) -> list[ControlDecision]:
        """Return the n most recent decisions."""
        decisions = list(self._decisions)
        return decisions[-n:] if len(decisions) >= n else decisions

    def get_recent_dicts(self, n: int = 5) -> list[dict]:
        """Return recent decisions as plain dicts (for prompt injection)."""
        return [
            {
                "timestep": d.timestep,
                "cooling_setpoint": d.cooling_setpoint,
                "heating_setpoint": d.heating_setpoint,
                "fan_speed": d.fan_speed,
                "reason": d.reason,
            }
            for d in self.get_recent(n)
        ]

    def get_average_setpoints(self) -> dict:
        """Compute average setpoints over the memory window."""
        if not self._decisions:
            return {}
        decisions = list(self._decisions)
        return {
            "avg_cooling": sum(d.cooling_setpoint for d in decisions) / len(decisions),
            "avg_heating": sum(d.heating_setpoint for d in decisions) / len(decisions),
            "avg_fan_speed": sum(d.fan_speed for d in decisions) / len(decisions),
        }

    def detect_oscillation(self, threshold: float = 2.0) -> bool:
        """
        Detect if setpoints are oscillating (sign of instability).
        Returns True if cooling setpoint variance is too high.
        """
        if len(self._decisions) < 4:
            return False
        recent = list(self._decisions)[-6:]
        values = [d.cooling_setpoint for d in recent]
        if len(values) < 2:
            return False
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return variance > threshold

    def clear(self) -> None:
        self._decisions.clear()

    def __len__(self) -> int:
        return len(self._decisions)

    def to_explanation_log(self) -> list[dict]:
        """Export full decision history as explanation log."""
        return [
            {
                "timestep": d.timestep,
                "timestamp": d.timestamp.isoformat(),
                "cooling_setpoint": d.cooling_setpoint,
                "heating_setpoint": d.heating_setpoint,
                "fan_speed": d.fan_speed,
                "airflow_m3s": d.airflow_m3s,
                "reason": d.reason,
                "llm_model": d.llm_model,
                "was_validated": d.was_validated,
                "validation_notes": d.validation_notes,
            }
            for d in self._decisions
        ]
