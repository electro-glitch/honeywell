# Architecture Reference

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    EnergyPlus Simulation                        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ BaseSimulation (ABC)                                      │  │
│  │  ├── EnergyPlusWrapper   (real EnergyPlus API)           │  │
│  │  └── MockSimulation      (synthetic physics model)       │  │
│  └───────────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │ register_timestep_callback()
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              MetricsCollector (callback)                        │
│  Reads: temperature, humidity, occupancy, CO₂, HVAC power      │
│  Computes: PMV (Fanger), PPD, carbon (gCO₂/kWh × kWh),        │
│            TOU electricity cost, comfort violations             │
│  Writes:  BuildingMetrics → SQLite                             │
│  Checks:  ComfortViolation → SQLite                            │
└────────────────────────┬────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 SQLite Database                                  │
│  Tables:                                                        │
│    simulation_runs       – run metadata + aggregate stats       │
│    building_metrics      – per-timestep sensor data            │
│    control_decisions     – LLM decisions + reasons             │
│    comfort_violations    – constraint violation records         │
└────────────────────────┬────────────────────────────────────────┘
                         │ repository.py queries
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 MCP Server (app/mcp/)                           │
│  Transport: stdio (in-process) or SSE                          │
│  8 registered tools with JSON Schema definitions               │
│  call_tool_direct() for in-process use (no network overhead)   │
└────────────────────────┬────────────────────────────────────────┘
                         │ tool responses (JSON)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              Decision Engine (app/agent/)                       │
│  DecisionEngine.decide(timestep):                              │
│    1. Should decide? (N-step interval check)                   │
│    2. call_tool_direct("read_latest_metrics")                  │
│    3. call_tool_direct("read_energy_history")                  │
│    4. Build prompt (metrics + history + memory + context)      │
│    5. OllamaClient.generate() or StubLLMClient                │
│    6. extract_json() → dict                                    │
│    7. _query_with_retry() (up to 3 self-correction attempts)  │
│    8. ControlValidator.validate_and_clamp()                    │
│    9. ControlDecision → SQLite                                 │
│   10. DecisionMemory.add()                                     │
└────────────────────────┬────────────────────────────────────────┘
                         │ ControlDecision
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│             ActuatorController (app/energyplus/)                │
│  sim.set_cooling_setpoint(decision.cooling_setpoint)           │
│  sim.set_heating_setpoint(decision.heating_setpoint)           │
│  sim.set_fan_speed(decision.fan_speed)                         │
│  sim.set_airflow(decision.airflow_m3s)                         │
└────────────────────────┬────────────────────────────────────────┘
                         │ applied at next timestep
                         └──────────────── LOOP ──────────────────┐
```

## Data Flow

### Baseline Mode
```
MockSimulation.run_simulation()
  → for each timestep:
      MetricsCollector.__call__(state)  # saves metrics
      baseline_callback(state)          # resets to defaults
```

### Optimized Mode
```
MockSimulation.run_simulation()
  → for each timestep:
      MetricsCollector.__call__(state)  # saves metrics
      optimization_callback(state):
        DecisionEngine.decide(timestep)
          → OllamaClient.generate(prompt)
          → extract_json(response)
          → ControlValidator.validate_and_clamp(data)
          → insert_decision(ControlDecision)
          → DecisionMemory.add(decision)
        ActuatorController.apply_setpoints(decision)
```

## Key Design Patterns

### Safety-First Validation
```
LLM Raw Output
  → extract_json()           # parse JSON from text
  → validate_and_clamp()     # clamp all values to safe ranges
  → dead band enforcement    # cooling ≥ heating + 2°C
  → absolute failsafe        # hard limits beyond config bounds
  → apply to simulation      # only after all checks pass
```

### Graceful Degradation
```
SIMULATION_MODE=energyplus → try EnergyPlusWrapper
  if ImportError or RuntimeError → MockSimulation

OLLAMA available → OllamaClient
  if not reachable → StubLLMClient (rule-based)

MCP SDK available → Full MCP protocol
  if not installed → call_tool_direct() passthrough
```

## Performance Notes

- MockSimulation: ~4,000 timesteps/sec (single core, no sleep)
- OllamaClient: ~2–8s per LLM call (model dependent)
- With query_every_n_steps=4: LLM overhead ≈ 25% of wall time
- SQLite: ~10,000 inserts/sec, sufficient for all timestep rates
- Dashboard generation: ~2–5s for 1-week simulation data
