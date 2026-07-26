# Eco-Loop System Architecture

This document provides a technical overview of the autonomous closed-loop control pipeline for the Honeywell Eco-Loop Building Agents challenge. It covers our integration of EnergyPlus 26.1 with an open-source LLM cognitive engine, focusing on the tool-calling architecture, prompt engineering strategies, latency management, and simulation log handling.

---

## 1. Tool-Calling Architecture & Communication Bus

The system uses the **Model Context Protocol (MCP)** to standardize communication between the EnergyPlus digital building sandbox and the LLM brain.

- **MCP Server Abstraction**: A lightweight embedded MCP server (`app/mcp/server.py`) registers 8 standardized tools including `read_latest_metrics`, `read_energy_history`, `update_setpoint`, and `modify_schedule`. Each tool is defined with a full JSON Schema for input validation.

- **In-Process Tool Calls**: During optimization, the `DecisionEngine` invokes tools via `call_tool_direct()` — a passthrough that skips network serialization entirely. This makes tool calls synchronous and zero-latency within the same process.

- **Forward Injection Loop**: After the LLM returns a validated JSON decision, setpoints are injected directly into the live EnergyPlus memory instance via the `pyenergyplus` Python API using EnergyPlus **Actuators**. No file I/O or simulation restart is needed — the updated setpoints take effect at the very next physics timestep.

---

## 2. Prompt Engineering Strategies

To ensure reliable, structured responses from open-source LLMs, we applied several prompt engineering paradigms:

- **Context-Aware Framing**: The `SYSTEM_PROMPT` (`app/agent/prompts.py`) defines a strict autonomous agent persona with explicit physical boundaries (PMV ±0.5, 22–25°C), economic constraints (TOU pricing tiers), and carbon intensity context. The LLM is instructed to respond *only* with valid JSON and never with explanatory prose.

- **Self-Correction Loops**: If the LLM produces invalid JSON, hallucinates field names, or suggests physically impossible setpoints, the engine automatically triggers a correction prompt (up to 3 retries) that feeds the specific error back to the model. After 3 failures, the system falls back to safe defaults — ensuring the simulation always continues.

- **Rolling Memory Injection**: The last 3 control decisions are dynamically injected into every prompt alongside a trend summary of the past 16 timesteps. This prevents the LLM from making rapid oscillatory decisions and provides the temporal gradient context ("temperature is rising at 0.3°C/step") needed for forward-looking control.

- **Minimal, Targeted Context**: Rather than dumping raw metrics, the prompt structures information into compact labeled sections (current state, trends, memory, constraints). This keeps token usage low and improves response quality on smaller open-source models.

---

## 3. Prompt Latency Management

Running 672 timesteps (168-hour simulation at 4 steps/hour) requires careful management of LLM inference latency.

- **Intermittent Polling**: The `DecisionEngine` only queries the LLM every `query_every_n_steps` timesteps (default: 4, configurable in `configs/llm.yaml`). During intermediate timesteps the simulation runs at previously established setpoints. This reduces LLM calls from 672 to ~168 per simulation.

- **Stub Fallback**: When Ollama is unavailable, the `StubLLMClient` applies deterministic rule-based heuristics (occupancy-weighted setback, temperature deadband logic) at zero inference latency. This makes end-to-end testing and CI runs fast and dependency-free.

- **Asynchronous-Ready Design**: The architecture separates simulation callbacks (synchronous, per-timestep) from LLM inference (I/O-bound). The current implementation runs synchronously within the EnergyPlus callback. The design is prepared for decoupling via `anyio` to allow the simulation to run ahead while LLM inference completes in the background.

---

## 4. Handling Lengthy Simulation Logs

EnergyPlus generates massive amounts of raw data over a 168-hour simulation. Sending full logs to the LLM would exceed context windows and degrade decision quality.

- **SQLite Metrics Database**: All real-time telemetry extracted from `pyenergyplus` is persisted every timestep into a lightweight SQLite database (`app/database/repository.py`). The schema has four tables: `simulation_runs`, `building_metrics`, `control_decisions`, and `comfort_violations`.

- **Targeted Retrieval via MCP**: When building a decision prompt, the `DecisionEngine` calls two MCP tools:
  - `read_latest_metrics` — returns a single JSON object with the most recent timestep values
  - `read_energy_history` — executes a SQL aggregation over the last N timesteps, returning min/max/avg/trend values rather than raw rows

- **Context Budget Control**: The aggregated history summary is bounded to a fixed number of timesteps regardless of simulation length. This means prompt token count is O(1) with respect to simulation duration — the LLM always receives the same amount of information whether the simulation has run for 1 hour or 1 week.

---

## 5. Safety Architecture

The system is designed to fail safely at every layer:

| Layer | Mechanism |
|-------|-----------|
| LLM output | `extract_json()` with regex fallback for partial responses |
| Field validation | Pydantic `ControlDecision` model rejects unknown/missing fields |
| Range clamping | `validate_and_clamp()` clips all setpoints to YAML-configured bounds |
| Dead-band | Cooling ≥ Heating + 2°C enforced after clamping |
| Hard limits | Absolute failsafe bounds applied as a final pass |
| Retry | Up to 3 self-correction retries before falling back to defaults |
| Simulation | EnergyPlus Actuator overrides are non-destructive — worst case: last valid setpoints persist |
