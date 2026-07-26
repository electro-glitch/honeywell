# Architecture Reference

## System Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    EnergyPlus Simulation Layer                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ BaseSimulation (ABC)                                      │  │
│  │  ├── EnergyPlusWrapper   (real EnergyPlus 26.1 API)      │  │
│  │  └── MockSimulation      (synthetic physics model)       │  │
│  └───────────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │ register_timestep_callback()
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              MetricsCollector (per-timestep callback)           │
│  Reads:    temperature, humidity, occupancy, CO₂, HVAC power   │
│  Computes: PMV (Fanger), PPD, carbon (gCO₂/kWh × kWh),        │
│            TOU electricity cost, comfort violations             │
│  Writes:   BuildingMetrics → SQLite                            │
│  Flags:    ComfortViolation records → SQLite                   │
└────────────────────────┬────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 SQLite Database (app/database/)                  │
│  simulation_runs    – run metadata + aggregate KPIs             │
│  building_metrics   – per-timestep sensor data                 │
│  control_decisions  – LLM decisions + reasoning text           │
│  comfort_violations – constraint violation records              │
└────────────────────────┬────────────────────────────────────────┘
                         │ repository.py SQL queries
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 MCP Server (app/mcp/)                           │
│  Transport: stdio (in-process) or standalone SSE               │
│  8 registered tools with JSON Schema definitions               │
│  call_tool_direct() bypasses network for in-process use        │
└────────────────────────┬────────────────────────────────────────┘
                         │ tool responses (JSON)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              Decision Engine (app/agent/)                       │
│  DecisionEngine.decide(timestep):                              │
│    1. Should decide? (N-step interval check)                   │
│    2. call_tool_direct("read_latest_metrics")                  │
│    3. call_tool_direct("read_energy_history")                  │
│    4. Build prompt (metrics + trend + memory + TOU + carbon)   │
│    5. OllamaClient.generate() or StubLLMClient (rule-based)   │
│    6. extract_json() → dict                                    │
│    7. _query_with_retry() — up to 3 self-correction attempts  │
│    8. ControlValidator.validate_and_clamp()                    │
│    9. ControlDecision → SQLite                                 │
│   10. DecisionMemory.add()                                     │
└────────────────────────┬────────────────────────────────────────┘
                         │ ControlDecision (validated setpoints)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│             ActuatorController (app/energyplus/)                │
│  sim.set_cooling_setpoint(decision.cooling_setpoint)           │
│  sim.set_heating_setpoint(decision.heating_setpoint)           │
│  sim.set_fan_speed(decision.fan_speed)                         │
│  sim.set_airflow(decision.airflow_m3s)                         │
└────────────────────────┬────────────────────────────────────────┘
                         │ injected into live EnergyPlus memory
                         └──────────────── LOOP ──────────────────┘
```

---

## Data Flow

### Baseline Mode

```
EnergyPlusWrapper.run_simulation()
  → for each timestep:
      MetricsCollector.__call__(state)   # saves metrics to SQLite
      baseline_callback(state)           # resets to default setpoints
```

### Optimized Mode

```
EnergyPlusWrapper.run_simulation()
  → for each timestep:
      MetricsCollector.__call__(state)   # saves metrics to SQLite
      optimization_callback(state):
        DecisionEngine.decide(timestep)
          → OllamaClient.generate(prompt)     # or StubLLMClient
          → extract_json(response)
          → ControlValidator.validate_and_clamp(data)
          → insert_decision(ControlDecision)
          → DecisionMemory.add(decision)
        ActuatorController.apply_setpoints(decision)
```

---

## Key Design Patterns

### Safety-First Validation

Every LLM output passes through a strict validation pipeline before being applied:

```
LLM raw text output
  → extract_json()              # parse JSON from free-form LLM text
  → validate_and_clamp()        # clamp all numeric values to YAML config bounds
  → dead-band enforcement       # cooling ≥ heating + 2°C (prevents oscillation)
  → absolute hard limits        # secondary failsafe beyond config bounds
  → apply to simulation         # only after all checks pass
```

### Graceful Degradation

The system is designed to run under any combination of available tools:

```
SIMULATION_MODE=energyplus → EnergyPlusWrapper
  if ImportError or RuntimeError → MockSimulation (synthetic physics)

OLLAMA available → OllamaClient (real LLM inference)
  if not reachable → StubLLMClient (deterministic rule-based heuristics)

MCP SDK available → Full MCP protocol (stdio transport)
  if not installed → call_tool_direct() passthrough (no network overhead)
```

### Prompt Context Assembly

Each LLM query packages the minimum context needed for a good decision:

```
prompt = SYSTEM_PROMPT
       + current_metrics        (latest zone state)
       + history_summary        (trend over last 16 timesteps)
       + decision_memory[-3:]   (last 3 decisions to avoid oscillation)
       + carbon_intensity        (gCO₂/kWh for current grid)
       + tou_tier               (off-peak / mid-peak / on-peak)
       + comfort_status         (current PMV, any active violations)
```

### Handling Long Simulation Logs

EnergyPlus generates thousands of data points per simulation. The system avoids context bloat through targeted retrieval:

- All real-time telemetry is persisted to SQLite via `MetricsCollector`
- `read_latest_metrics` returns only the single most recent timestep
- `read_energy_history` returns an aggregated window (e.g. last 16 steps) — not raw rows
- The LLM never sees raw log files; it only sees structured, pre-summarized JSON

---

## Performance Characteristics

| Component | Performance |
|-----------|------------|
| EnergyPlusWrapper | Governed by EnergyPlus engine speed (~1–4× real time for 1-week sim) |
| MockSimulation | ~4,000 timesteps/sec (pure Python, single core) |
| OllamaClient (Llama 3 8B) | ~2–8s per LLM call depending on hardware |
| With query_every_n_steps=4 | LLM overhead ≈ 25% of total wall time |
| SQLite writes | ~10,000 inserts/sec — sufficient for all timestep rates |
| Dashboard generation | ~2–5s for a 1-week simulation dataset |
