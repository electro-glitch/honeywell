"""
Ollama LLM Client
==================
Handles all communication with the Ollama API.
Supports model switching, retries, and response parsing.

Supported models: llama3, mistral, qwen2.5, llama3.2, phi3
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from app.config import LLMConfig, get_config


class OllamaClient:
    """
    HTTP client for Ollama REST API.

    Endpoints used:
      POST /api/generate — text generation (non-streaming)
      GET  /api/tags     — list available models
    """

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or get_config().llm
        self.base_url = self.config.base_url.rstrip("/")
        self._client = httpx.Client(timeout=self.config.timeout)

    def is_available(self) -> bool:
        """Check if Ollama is running and reachable."""
        try:
            resp = self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Return list of available Ollama model names."""
        try:
            resp = self._client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Generate a completion from Ollama.
        Returns the response text string.
        """
        model = model or self.config.model
        temperature = temperature if temperature is not None else self.config.temperature
        max_tokens = max_tokens or self.config.max_tokens

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": self.config.top_p,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        logger.debug(f"Ollama request: model={model}, prompt_len={len(prompt)}")
        start = time.monotonic()

        try:
            resp = self._client.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.config.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "")
            elapsed = time.monotonic() - start
            logger.debug(
                f"Ollama response: {len(text)} chars in {elapsed:.2f}s "
                f"(eval_count={data.get('eval_count', '?')})"
            )
            return text
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Ollama HTTP error {e.response.status_code}: {e.response.text}") from e
        except httpx.TimeoutException:
            raise LLMError(f"Ollama request timed out after {self.config.timeout}s") from None
        except Exception as e:
            raise LLMError(f"Ollama request failed: {e}") from e

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """
        Use Ollama chat endpoint (for models that support it).
        messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
        """
        model = model or self.config.model
        temperature = temperature if temperature is not None else self.config.temperature

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "top_p": self.config.top_p},
        }

        try:
            resp = self._client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.config.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        except Exception as e:
            raise LLMError(f"Ollama chat failed: {e}") from e

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class LLMError(Exception):
    """Raised when LLM communication or parsing fails."""


def extract_json(text: str) -> dict:
    """
    Extract the first valid JSON object from a text string.
    Handles cases where the LLM wraps JSON in markdown code blocks.
    """
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*", "", text)

    # Try to find JSON object
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Try to parse the whole text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    raise LLMError(f"No valid JSON found in LLM response: {text[:200]}")


# ── Stub Client (when Ollama is not available) ────────────────────────────────

class StubLLMClient:
    """
    Fallback LLM that returns rule-based decisions.
    Used when Ollama is not running.
    """

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or get_config().llm
        logger.warning(
            "Ollama not available — using StubLLMClient (rule-based decisions). "
            "Start Ollama and run `ollama pull llama3` for real LLM decisions."
        )

    def is_available(self) -> bool:
        return True  # Stub is always "available"

    def generate(self, prompt: str, system: str | None = None, **kwargs) -> str:
        """Generate a rule-based decision from the prompt context."""
        decision = self._rule_based_decision(prompt)
        return json.dumps(decision)

    def _rule_based_decision(self, prompt: str) -> dict:
        """Extract key metrics from prompt and apply simple rules."""
        import re

        def _extract(pattern: str, default: float) -> float:
            m = re.search(pattern, prompt)
            return float(m.group(1)) if m else default

        indoor = _extract(r"Indoor Temperature: ([\d.]+)°C", 23.0)
        pmv = _extract(r"PMV.*?: ([-\d.]+)", 0.0)
        occupancy = _extract(r"Occupancy: ([\d.]+)%", 50.0) / 100.0
        co2 = _extract(r"CO₂.*?: ([\d.]+) ppm", 500.0)

        # Rule-based logic
        cool_sp = 24.0
        heat_sp = 20.0
        fan = 0.6
        reason_parts = []

        if occupancy < 0.05:
            cool_sp = 27.0
            heat_sp = 16.0
            fan = 0.2
            reason_parts.append("unoccupied setback")
        else:
            if pmv > 0.5:
                cool_sp = max(18.0, 24.0 - (pmv - 0.5) * 2)
                fan = min(1.0, fan + 0.2)
                reason_parts.append(f"PMV too high ({pmv:.2f}), cooling")
            elif pmv < -0.5:
                heat_sp = min(24.0, 20.0 + abs(pmv + 0.5) * 2)
                reason_parts.append(f"PMV too low ({pmv:.2f}), heating")
            else:
                # Comfort OK — optimize for energy
                cool_sp = min(26.0, cool_sp + 0.5)
                fan = max(0.3, fan - 0.1)
                reason_parts.append("comfort OK, saving energy")

            if co2 > 900:
                fan = min(1.0, fan + 0.3)
                reason_parts.append(f"high CO₂ ({co2:.0f} ppm), increasing ventilation")

        return {
            "cooling_setpoint": round(cool_sp, 1),
            "heating_setpoint": round(heat_sp, 1),
            "fan_speed": round(fan, 2),
            "airflow_m3s": round(0.3 + occupancy * 0.4, 2),
            "reason": "; ".join(reason_parts) or "maintaining defaults",
        }

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def create_llm_client(config: Optional[LLMConfig] = None) -> OllamaClient | StubLLMClient:
    """
    Factory: create the appropriate LLM client.
    Returns OllamaClient if Ollama is running, otherwise StubLLMClient.
    """
    config = config or get_config().llm
    client = OllamaClient(config)
    if client.is_available():
        logger.info(f"Ollama connected — using model: {config.model}")
        return client
    else:
        logger.warning(f"Ollama not reachable at {config.base_url}")
        return StubLLMClient(config)
