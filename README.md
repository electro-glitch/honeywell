# 🏢 Eco-Loop Building Agents

> **Autonomous AI Building Optimization System**  
> EnergyPlus 26.1 · Python 3.12 · Open-Source LLM (Ollama) · MCP Server · Closed-Loop Control

[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![EnergyPlus](https://img.shields.io/badge/EnergyPlus-26.1-orange.svg)](https://energyplus.net)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [EnergyPlus Setup](#energyplus-setup)
- [Ollama LLM Setup](#ollama-llm-setup)
- [Running Simulations](#running-simulations)
- [Dashboard](#dashboard)
- [Reports](#reports)
- [MCP Server](#mcp-server)
- [LLM Integration](#llm-integration)
- [Configuration](#configuration)
- [Docker](#docker)
- [Testing](#testing)
- [Key Features](#key-features)
- [Future Work](#future-work)

---

## Overview

**Eco-Loop Building Agents** is an autonomous HVAC optimization system that pairs a physics-accurate building simulation with an open-source LLM reasoning engine to continuously minimize energy consumption while maintaining occupant comfort.

- **EnergyPlus 26.1** (or built-in mock) for high-fidelity building simulation
- **Local LLM** (via Ollama — Llama 3, Mistral, Qwen 2.5) for intelligent control decisions
- **MCP (Model Context Protocol)** as the tool interface between the LLM and building data
- **Closed-loop control** — the agent observes metrics every N timesteps, reasons about building state, and injects updated HVAC setpoints back into the live simulation

The default configuration targets a **medium office building in New Delhi**, running a full 168-hour (1-week) simulation against the `ZoneCoupledKivaRefBldgMediumOffice` ASHRAE reference IDF.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    EnergyPlus Simulation                        │
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
│  Reads: temperature, humidity, occupancy, CO₂, HVAC power      │
│  Computes: PMV (Fanger), PPD, carbon (gCO₂/kWh × kWh),        │
│            TOU electricity cost, comfort violations             │
│  Writes:   BuildingMetrics → SQLite                            │
└────────────────────────┬────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 SQLite Database                                  │
│  simulation_runs    – run metadata + aggregate KPIs             │
│  building_metrics   – per-timestep sensor data                 │
│  control_decisions  – LLM decisions + reasoning text           │
│  comfort_violations – constraint violation records              │
└────────────────────────┬────────────────────────────────────────┘
                         │ repository.py queries
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 MCP Server (app/mcp/)                           │
│  8 registered tools with JSON Schema definitions               │
│  call_tool_direct() for in-process use (no network overhead)   │
└────────────────────────┬────────────────────────────────────────┘
                         │ tool responses (JSON)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              Decision Engine (app/agent/)                       │
│    1. Should decide? (N-step interval check)                   │
│    2. read_latest_metrics via MCP tool                         │
│    3. read_energy_history via MCP tool                         │
│    4. Build prompt (metrics + trend + memory + TOU + carbon)   │
│    5. OllamaClient.generate() or StubLLMClient (rule-based)   │
│    6. extract_json() + _query_with_retry() (up to 3 attempts) │
│    7. ControlValidator.validate_and_clamp()                    │
│    8. ControlDecision → SQLite + DecisionMemory                │
└────────────────────────┬────────────────────────────────────────┘
                         │ validated setpoints
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│             ActuatorController (app/energyplus/)                │
│  sim.set_cooling_setpoint / set_heating_setpoint               │
│  sim.set_fan_speed / set_airflow                               │
└────────────────────────┬────────────────────────────────────────┘
                         │ injected at next EnergyPlus timestep
                         └──────────────── LOOP ──────────────────┘
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| CLI | Typer + Rich |
| Simulation | EnergyPlus 26.1 / Mock |
| Building Model | ASHRAE MediumOffice IDF |
| Weather | New Delhi TMYx EPW |
| LLM | Ollama (Llama 3, Mistral, Qwen 2.5) |
| MCP | MCP Python SDK |
| Database | SQLite + aiosqlite |
| Data | Pandas + NumPy + SciPy |
| Visualization | Plotly (interactive HTML dashboard) |
| Reporting | Jinja2 + WeasyPrint (MD / HTML / PDF / CSV) |
| Validation | Pydantic v2 |
| Logging | Loguru |
| Retries | Tenacity |
| Container | Docker + docker-compose |
| Testing | pytest + pytest-asyncio |
| Linting | Ruff |

---

## Project Structure

```
eco-loop/
├── app/
│   ├── agent/
│   │   ├── llm_client.py        # Ollama HTTP client + StubLLMClient fallback
│   │   ├── prompts.py           # System & decision prompt templates
│   │   ├── memory.py            # Sliding-window decision history
│   │   └── decision_engine.py   # LLM query + JSON extraction + retry logic
│   ├── controllers/
│   │   ├── validator.py         # Safety constraint enforcement + dead-band
│   │   └── control_loop.py      # Main OptimizationLoop orchestrator
│   ├── dashboard/
│   │   ├── dashboard.py         # Self-contained HTML dashboard generator
│   │   ├── plots.py             # Individual Plotly chart functions
│   │   └── reporter.py          # MD / HTML / PDF / CSV report generator
│   ├── database/
│   │   ├── db.py                # SQLite connection + schema init
│   │   ├── models.py            # Pydantic data models
│   │   └── repository.py        # CRUD operations + analytical queries
│   ├── energyplus/
│   │   ├── wrapper.py           # EnergyPlus 26.1 API wrapper + MockSimulation
│   │   ├── metrics_collector.py # Per-timestep PMV/energy data collection
│   │   └── actuators.py         # Setpoint injection into live simulation
│   ├── mcp/
│   │   ├── server.py            # MCP server (8 tools, stdio transport)
│   │   ├── tools.py             # Tool implementations
│   │   └── schemas.py           # Pydantic I/O schemas for all tools
│   ├── utils/
│   │   └── parser.py            # Data parsing utilities
│   ├── config.py                # Centralized config (YAML + .env overlay)
│   └── logging_config.py        # Loguru setup
├── configs/
│   ├── settings.yaml            # App-level settings
│   ├── simulation.yaml          # HVAC constraints, comfort bounds, occupancy
│   └── llm.yaml                 # LLM model config, decision interval
├── data/
│   ├── idf/                     # EnergyPlus IDF building models
│   └── weather/                 # EPW weather files (New Delhi TMYx)
├── tests/
│   ├── conftest.py              # Shared pytest fixtures
│   ├── unit/                    # Fast unit tests (no EnergyPlus required)
│   └── integration/             # End-to-end loop tests
├── outputs/                     # Generated dashboards, CSVs, reports
├── docs/                        # Architecture reference documentation
├── .github/workflows/ci.yml     # GitHub Actions CI pipeline
├── Dockerfile
├── docker-compose.yml
├── main.py                      # Typer CLI entry point
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Prerequisites

- Python 3.12+
- [EnergyPlus 26.1](https://energyplus.net/downloads) installed at `C:/EnergyPlusV26-1-0`
- [Ollama](https://ollama.ai/) for local LLM inference (optional — stub fallback available)

---

## Installation

```bash
# Clone the repository
git clone https://github.com/electro-glitch/honeywell.git
cd honeywell/eco-loop

# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env as needed
```

---

## EnergyPlus Setup

The system defaults to `energyplus` mode using the bundled IDF and EPW files.

**Required:**
- EnergyPlus 26.1 installed at `C:/EnergyPlusV26-1-0` (or update `energyplus_dir` in `configs/simulation.yaml`)
- IDF: `data/idf/ZoneCoupledKivaRefBldgMediumOffice.idf`
- EPW: `data/weather/IND_DL_New.Delhi-Gandhi.Intl.AP.421810_TMYx.2004-2018.epw`

To switch to mock mode (no EnergyPlus required):
```bash
python main.py baseline --mode mock
python main.py optimize --mode mock
```

---

## Ollama LLM Setup

```bash
# Install Ollama (Linux/Mac)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3          # Meta Llama 3 8B (recommended)
ollama pull mistral         # Mistral 7B
ollama pull qwen2.5         # Alibaba Qwen 2.5 7B

# Verify Ollama is running
ollama list
```

> **No Ollama?** The system automatically falls back to a rule-based `StubLLMClient` that applies heuristic HVAC control — suitable for testing and demos.

---

## Running Simulations

### Baseline (fixed setpoints, no LLM)

```bash
python main.py baseline
python main.py baseline --hours 168 --mode energyplus
```

Runs EnergyPlus with fixed default setpoints. Results are stored in SQLite and exported to `outputs/baseline.csv`.

### Optimization (LLM-driven)

```bash
python main.py optimize
python main.py optimize --model qwen2.5 --hours 168
```

The LLM agent reads metrics every 4 timesteps via MCP tools and adjusts HVAC setpoints. Results stored in SQLite and exported to `outputs/optimized.csv`.

### Full Comparison

```bash
python main.py compare
python main.py compare --hours 168 --mode energyplus
```

Runs baseline then optimization sequentially, prints a savings summary, and generates `outputs/comparison.csv`.

### Simulation History

```bash
python main.py status
python main.py status --limit 20
```

---

## Dashboard

```bash
python main.py dashboard
python main.py dashboard --simulation-id optimized_abc123 --no-open-browser
```

Generates a self-contained interactive HTML dashboard at `outputs/dashboard.html` (~700 KB). Includes:

- Energy savings KPI cards (kWh saved, cost saved, carbon reduced)
- Cumulative energy: baseline vs. optimized
- Zone temperature timeline with comfort band overlay
- PMV comfort index over time
- HVAC power usage
- Occupancy profile
- Carbon emissions comparison
- Energy breakdown (HVAC / lighting / equipment)
- Comfort violations timeline

---

## Reports

```bash
python main.py report                                        # Markdown (default)
python main.py report --format html                          # HTML with styling
python main.py report --format pdf                           # PDF (requires WeasyPrint)
python main.py report --format csv                           # Raw CSV export
python main.py report --simulation-id optimized_abc123 --format pdf
```

Reports include an executive summary (natural language), energy performance table, comfort statistics, and recommendations.

---

## MCP Server

The embedded MCP server exposes 8 tools used by the LLM agent:

| Tool | Description |
|------|-------------|
| `read_latest_metrics` | Current zone temperature, energy, PMV, CO₂, humidity |
| `read_energy_history` | Historical trend data (last N timesteps, aggregated) |
| `update_setpoint` | Set cooling / heating / fan setpoints |
| `modify_schedule` | Adjust occupancy schedule |
| `run_simulation_step` | Advance simulation N timesteps |
| `restart_simulation` | Reset and restart the simulation |
| `generate_dashboard` | Trigger dashboard generation |
| `save_report` | Generate a report in the specified format |

To expose the MCP server over stdio for external clients:

```bash
python main.py mcp-server
```

---

## LLM Integration

The agent runs this reasoning loop at every N-th timestep:

```
1. read_latest_metrics  → current zone state
2. read_energy_history  → rolling trend summary
3. Build prompt:
   - Current metrics (temp, PMV, CO₂, HVAC power, occupancy)
   - Trend summary (rising/falling gradients)
   - Rolling decision memory (last 20 decisions)
   - Carbon intensity context
   - TOU electricity pricing tier
4. Query LLM → structured JSON decision
5. validate_and_clamp() → enforce comfort + safety bounds
6. Apply setpoints to live simulation
7. Store ControlDecision in DB + DecisionMemory
```

**Key safety rules enforced by the validator:**
- PMV must stay within −0.5 to +0.5
- Zone temperature must stay 22–25°C during occupancy
- Cooling setpoint ≥ heating setpoint + 2°C (dead band)
- Aggressive setback during unoccupied hours

**Self-correction:** On invalid JSON or missing fields, the engine retries up to 3 times, feeding the error context back to the model. On persistent failure it falls back to safe defaults.

---

## Configuration

### `configs/simulation.yaml`

```yaml
simulation:
  mode: energyplus            # "mock" | "energyplus"
  total_hours: 168            # 1 week
  timesteps_per_hour: 4
  idf_file: data/idf/ZoneCoupledKivaRefBldgMediumOffice.idf
  epw_file: data/weather/IND_DL_New.Delhi-Gandhi.Intl.AP.421810_TMYx.2004-2018.epw
  energyplus_dir: C:/EnergyPlusV26-1-0

hvac:
  cooling_setpoint: { min: 18.0, max: 28.0, default: 24.0 }
  heating_setpoint: { min: 15.0, max: 28.0, default: 20.0 }
  fan_speed:        { min: 0.0,  max: 1.0,  default: 0.7  }
  airflow:          { min: 0.0,  max: 10.0, default: 0.5  }

comfort:
  pmv_min: -0.5
  pmv_max: 0.5
  temp_min_c: 22.0
  temp_max_c: 25.0
  co2_max_ppm: 1000.0
```

### `configs/llm.yaml`

```yaml
llm:
  model: llama3
  temperature: 0.2

decision:
  query_every_n_steps: 4    # Query LLM every 4 timesteps (~1 simulated hour)
  memory_size: 20           # Remember last 20 decisions for context
```

All values can be overridden with environment variables (see `.env.example`).

---

## Docker

```bash
# Build and run with docker-compose (includes Ollama sidecar)
docker-compose up --build

# Run a specific command
docker run eco-loop optimize --hours 24 --model llama3

# Pull an LLM model into the running Ollama container
docker-compose exec ollama ollama pull llama3
```

---

## Testing

```bash
# All tests
pytest

# Unit tests only (no EnergyPlus required)
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# With coverage report
pytest --cov=app --cov-report=html
```

---

## Key Features

| Feature | Description |
|---------|-------------|
| Real EnergyPlus integration | Full `pyenergyplus` API binding with actuator injection into live simulation memory |
| Mock simulation fallback | Synthetic physics model — no EnergyPlus install required |
| LLM stub fallback | Rule-based `StubLLMClient` — no Ollama required |
| Safety-first validation | All LLM outputs clamped, dead-band enforced, hard limits applied before use |
| Self-correcting retries | Up to 3 LLM retries with error context before falling back to safe defaults |
| Decision memory | Sliding window of last N decisions injected into every prompt |
| Carbon-aware optimization | Real-time carbon intensity (gCO₂/kWh) included in LLM context |
| TOU electricity pricing | Off-peak / mid-peak / on-peak tariff tiers influence setpoint decisions |
| Interactive HTML dashboard | Self-contained ~700 KB Plotly dashboard, no server required |
| Multi-format reporting | Markdown, HTML, PDF, CSV reports with NLG executive summaries |
| SQLite persistence | All metrics, decisions, and violations stored for post-hoc analysis |

---

## Future Work

1. **Multi-zone control** — extend to buildings with multiple thermal zones
2. **Real-time weather API** — integrate Open-Meteo for live forecast pre-conditioning
3. **Grid-interactive** — real-time carbon intensity from ElectricityMap API
4. **Reinforcement learning** — replace LLM with RL agent for continuous policy learning
5. **Fault detection** — LLM-based anomaly detection in sensor data
6. **Digital twin sync** — bi-directional BMS integration via BACnet/Modbus
7. **Multi-building fleet** — portfolio-scale agent with centralized coordination
8. **Natural language control** — "make the east wing warmer" → automated setpoint change
