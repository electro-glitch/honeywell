"""
Decision Engine
================
The core reasoning component of Eco-Loop.

Every N timesteps:
  1. Reads current metrics via MCP tool
  2. Builds context prompt
  3. Queries LLM for a structured JSON decision
  4. Validates the decision against safety constraints
  5. Applies controls via the actuator controller

Includes:
  - Self-correcting retries (up to 3 attempts)
  - Memory of previous decisions
  - Bonus: carbon-aware and price-aware reasoning context
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from loguru import logger

from app.agent.llm_client import (
    LLMError,
    OllamaClient,
    StubLLMClient,
    create_llm_client,
    extract_json,
)
from app.agent.memory import DecisionMemory
from app.agent.prompts import SELF_CORRECTION_PROMPT, SYSTEM_PROMPT, build_decision_prompt
from app.config import LLMConfig, get_config
from app.database.models import ControlDecision
from app.database.repository import insert_decision
from app.mcp.server import call_tool_direct


class DecisionEngine:
    """
    Autonomous building optimization decision engine.

    Queries the LLM at configurable intervals to determine optimal
    HVAC setpoints based on current and historical building state.
    """

    def __init__(
        self,
        simulation_id: str,
        llm_client: OllamaClient | StubLLMClient | None = None,
        config: LLMConfig | None = None,
    ) -> None:
        self.simulation_id = simulation_id
        self._cfg = config or get_config().llm
        self._llm = llm_client or create_llm_client(self._cfg)
        self._memory = DecisionMemory(max_size=self._cfg.memory_size)
        self._step_counter = 0
        self._last_decision: ControlDecision | None = None
        self._total_decisions = 0
        self._failed_decisions = 0

    @property
    def memory(self) -> DecisionMemory:
        return self._memory

    def should_decide(self, timestep: int) -> bool:
        """
        Determine if the LLM should be queried this timestep.
        Uses configurable N-step interval; always queries on first step.
        """
        if self._cfg.always_reason:
            return True
        return timestep % self._cfg.query_every_n_steps == 0

    def decide(self, timestep: int) -> ControlDecision | None:
        """
        Query LLM for a control decision at the given timestep.

        Returns a validated ControlDecision, or None if the LLM
        is unavailable or all retries fail.
        """
        if not self.should_decide(timestep):
            return self._last_decision

        # Gather context via MCP tools
        metrics = call_tool_direct("read_latest_metrics", {"simulation_id": self.simulation_id})
        if "error" in metrics:
            logger.warning(f"Cannot get metrics for decision: {metrics['error']}")
            return self._last_decision

        history = call_tool_direct(
            "read_energy_history",
            {"simulation_id": self.simulation_id, "last_n": self._cfg.query_every_n_steps * 4},
        )

        # Build prompt
        history_summary = {
            "avg_indoor_temp_c": history.get("avg_indoor_temp_c"),
            "avg_pmv": history.get("avg_pmv"),
            "total_energy_kwh": history.get("total_energy_kwh"),
        }

        carbon_intensity = get_config().carbon.intensity_g_per_kwh
        electricity_price = metrics.get("electricity_cost")

        prompt = build_decision_prompt(
            metrics=metrics,
            history_summary=history_summary,
            recent_decisions=self._memory.get_recent_dicts(3),
            carbon_intensity=carbon_intensity,
            electricity_price=electricity_price,
        )

        # Query LLM with retries
        decision_data = self._query_with_retry(prompt)

        if decision_data is None:
            self._failed_decisions += 1
            logger.warning(f"All LLM retries failed at timestep {timestep}")
            return self._last_decision

        # Build and validate decision
        decision = self._build_decision(decision_data, timestep)
        if decision is None:
            return self._last_decision

        # Persist to database
        insert_decision(decision)

        # Update memory
        self._memory.add(decision)
        self._last_decision = decision
        self._total_decisions += 1

        logger.info(
            f"Decision [{timestep}]: cool={decision.cooling_setpoint}°C "
            f"heat={decision.heating_setpoint}°C fan={decision.fan_speed:.2f} "
            f"— {decision.reason[:60]}"
        )

        return decision

    def _query_with_retry(self, prompt: str) -> dict | None:
        """Query the LLM with up to max_attempts retries for valid JSON."""
        max_attempts = self._cfg.max_attempts

        for attempt in range(max_attempts):
            try:
                if attempt == 0:
                    text = self._llm.generate(prompt=prompt, system=SYSTEM_PROMPT)
                else:
                    # Self-correction: send the invalid response back with guidance
                    correction_prompt = (
                        f"{prompt}\n\nPrevious response was invalid. {SELF_CORRECTION_PROMPT}"
                    )
                    text = self._llm.generate(prompt=correction_prompt, system=SYSTEM_PROMPT)

                data = extract_json(text)

                # Quick sanity check on required fields
                required = {"cooling_setpoint", "heating_setpoint", "fan_speed", "reason"}
                if required.issubset(data.keys()):
                    if attempt > 0:
                        logger.info(f"LLM self-corrected on attempt {attempt + 1}")
                    return data
                else:
                    missing = required - data.keys()
                    logger.warning(f"LLM JSON missing fields: {missing} (attempt {attempt + 1})")

            except LLMError as e:
                logger.warning(f"LLM attempt {attempt + 1}/{max_attempts} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(self._cfg.wait_seconds)

        return None

    def _build_decision(
        self,
        data: dict,
        timestep: int,
    ) -> ControlDecision | None:
        """
        Build a ControlDecision from raw LLM output.
        Validates ranges before constructing the model.
        """
        from app.controllers.validator import ControlValidator

        validator = ControlValidator()
        validated, notes = validator.validate_and_clamp(data)

        try:
            decision = ControlDecision(
                simulation_id=self.simulation_id,
                timestep=timestep,
                timestamp=datetime.utcnow(),
                cooling_setpoint=validated["cooling_setpoint"],
                heating_setpoint=validated["heating_setpoint"],
                fan_speed=validated["fan_speed"],
                airflow_m3s=validated.get("airflow_m3s"),
                reason=data.get("reason", "No reason provided"),
                llm_model=self._cfg.model,
                raw_response=json.dumps(data),
                was_validated=True,
                validation_notes=notes or None,
                carbon_intensity_g_kwh=get_config().carbon.intensity_g_per_kwh,
            )
            return decision
        except Exception as e:
            logger.error(f"Failed to build ControlDecision: {e}")
            return None

    def get_stats(self) -> dict:
        """Return decision engine statistics."""
        return {
            "simulation_id": self.simulation_id,
            "total_decisions": self._total_decisions,
            "failed_decisions": self._failed_decisions,
            "memory_size": len(self._memory),
            "oscillation_detected": self._memory.detect_oscillation(),
            "llm_model": self._cfg.model,
        }
