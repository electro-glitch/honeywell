# 🏢 Eco-Loop Building Agents

> **Autonomous AI Building Optimization System**  
> Using EnergyPlus · Python 3.12 · Open-Source LLM · MCP Server · Closed-Loop Control

[![CI](https://github.com/your-org/eco-loop/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/eco-loop/actions)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
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
- [Bonus Features](#bonus-features)
- [Future Work](#future-work)

---

## Overview

**Eco-Loop Building Agents** is a hackathon-ready proof-of-concept demonstrating autonomous building HVAC optimization using:

- **EnergyPlus** (or built-in mock) for high-fidelity building simulation
- **Local LLM** (via Ollama — Llama 3, Mistral, Qwen) for intelligent control decisions
- **MCP (Model Context Protocol)** as the tool interface between the LLM and building data
- **Closed-loop control** — continuously observing, reasoning, and adjusting setpoints

The system can achieve **10–25% energy savings** compared to fixed-setpoint baseline operation while maintaining occupant comfort (PMV ±0.5, 22–25°C).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    EnergyPlus Simulation                        │
│            (real EnergyPlus or built-in mock)                  │
└────────────────────────┬────────────────────────────────────────┘
                         │ Python API callbacks
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              EnergyPlus Python API Wrapper                      │
│         (app/energyplus/wrapper.py, actuators.py)              │
└────────────────────────┬────────────────────────────────────────┘
                         │ per-timestep metrics
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              Runtime Metrics Stream                              │
│            (app/energyplus/metrics_collector.py)               │
│   PMV · Temperature · Energy · CO₂ · Occupancy · Carbon        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│               SQLite Local Database                              │
│         (app/database/db.py, repository.py)                    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Server                                   │
│              (app/mcp/server.py, tools.py)                     │
│  Tools: read_latest_metrics · read_energy_history ·            │
│         update_setpoint · modify_schedule · run_simulation_step │
│         restart_simulation · generate_dashboard · save_report   │
└────────────────────────┬────────────────────────────────────────┘
                         │ tool calls
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              Local Open-Source LLM (Ollama)                     │
│           Llama 3 · Mistral · Qwen · Phi-3                     │
└────────────────────────┬────────────────────────────────────────┘
                         │ structured JSON decision
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Decision Engine                                │
│              (app/agent/decision_engine.py)                    │
│   LLM reasoning → JSON → Validator → ControlDecision           │
└────────────────────────┬────────────────────────────────────────┘
                         │ validated setpoints
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Actuator Controller                             │
│              (app/energyplus/actuators.py)                     │
└────────────────────────┬────────────────────────────────────────┘
                         │ inject into simulation
                         ▼
                 Next Simulation Timestep
                         │
                         └─────── REPEAT ──────────────────────┐
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| CLI | Typer |
| API | FastAPI |
| Simulation | EnergyPlus 24.1 / Mock |
| LLM | Ollama (Llama 3, Mistral, Qwen 2.5) |
| MCP | MCP Python SDK |
| Database | SQLite + aiosqlite |
| Data | Pandas + NumPy |
| Visualization | Plotly + Matplotlib |
| Reporting | Jinja2 + WeasyPrint |
| Validation | Pydantic v2 |
| Logging | Loguru |
| Retries | Tenacity |
| Packaging | uv |
| Container | Docker |
| CI | GitHub Actions |
| Testing | pytest + pytest-asyncio |
| Linting | Ruff |

---

## Project Structure

```
eco-loop/
├── app/
│   ├── energyplus/
│   │   ├── wrapper.py          # EnergyPlus + Mock simulation backend
│   │   ├── metrics_collector.py # Timestep data collection + PMV calc
│   │   └── actuators.py        # Setpoint injection
│   ├── agent/
│   │   ├── llm_client.py       # Ollama HTTP client + stub fallback
│   │   ├── prompts.py          # System & decision prompts
│   │   ├── memory.py           # Sliding-window decision history
│   │   └── decision_engine.py  # LLM query + validation orchestration
│   ├── mcp/
│   │   ├── server.py           # MCP server (8 tools)
│   │   ├── tools.py            # Tool implementations
│   │   └── schemas.py          # Pydantic I/O schemas
│   ├── controllers/
│   │   ├── validator.py        # Safety constraint enforcement
│   │   └── control_loop.py     # Main optimization orchestrator
│   ├── database/
│   │   ├── db.py               # SQLite connection + schema
│   │   ├── models.py           # Pydantic data models
│   │   └── repository.py       # CRUD + queries
│   ├── dashboard/
│   │   ├── dashboard.py        # HTML dashboard generator
│   │   ├── plots.py            # Individual Plotly chart functions
│   │   └── reporter.py         # MD / HTML / PDF / CSV reports
│   ├── utils/
│   │   └── parser.py           # Data parsing utilities
│   ├── config.py               # Centralized config (YAML + env)
│   └── logging_config.py       # Loguru setup
├── configs/
│   ├── settings.yaml           # App-level settings
│   ├── simulation.yaml         # HVAC constraints, comfort bounds
│   └── llm.yaml                # Model config, few-shot examples
├── data/
│   ├── idf/                    # EnergyPlus IDF building models
│   └── weather/                # EPW weather files
├── tests/
│   ├── conftest.py             # Shared fixtures
│   ├── unit/                   # Fast unit tests (no EnergyPlus)
│   └── integration/            # End-to-end loop tests
├── outputs/                    # Generated reports, CSVs, plots
├── docs/                       # Additional documentation
├── .github/workflows/ci.yml    # GitHub Actions CI
├── Dockerfile                  # Production Docker image
├── docker-compose.yml          # Full stack (app + Ollama)
├── main.py                     # Typer CLI entry point
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [Ollama](https://ollama.ai/) for local LLM (optional — stub fallback available)
- [EnergyPlus](https://energyplus.net/) 24.1+ (optional — mock mode available)

---

## Installation

### Option 1: Using uv (recommended)

```bash
# Clone the repository
git clone https://github.com/your-org/eco-loop.git
cd eco-loop

# Create virtual environment and install
uv venv
uv pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your settings
```

### Option 2: Using pip

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

---

## EnergyPlus Setup

EnergyPlus is **optional**. The system runs in `mock` mode by default.

### To use real EnergyPlus:

1. Download EnergyPlus 24.1 from [energyplus.net](https://energyplus.net/downloads)
2. Install to e.g. `/usr/local/EnergyPlus-24-1-0` (Linux/Mac) or `C:\EnergyPlusV24-1-0` (Windows)
3. Set in `.env`:
   ```
   ENERGYPLUS_DIR=/usr/local/EnergyPlus-24-1-0
   SIMULATION_MODE=energyplus
   ```
4. Place your IDF and EPW files in `data/idf/` and `data/weather/`
5. Update `configs/simulation.yaml` with file paths

---

## Ollama LLM Setup

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model (choose one)
ollama pull llama3          # Meta Llama 3 8B (recommended)
ollama pull mistral         # Mistral 7B
ollama pull qwen2.5         # Alibaba Qwen 2.5 7B
ollama pull phi3            # Microsoft Phi-3 Mini

# Verify
ollama list
ollama serve  # Should already be running as a service
```

Configure in `.env` or `configs/llm.yaml`:
```yaml
llm:
  model: llama3      # or mistral, qwen2.5, phi3
  base_url: http://localhost:11434
  temperature: 0.2
```

> **No Ollama?** The system automatically falls back to a rule-based `StubLLMClient` that applies heuristic HVAC control — perfect for demos!

---

## Running Simulations

### Baseline (no LLM)

```bash
python main.py baseline
python main.py baseline --hours 168 --mode mock
```

Runs EnergyPlus (or mock) with fixed default setpoints. Stores results in SQLite and exports `outputs/baseline.csv`.

### Optimization (with LLM)

```bash
python main.py optimize
python main.py optimize --model qwen2.5 --hours 168
```

Runs the LLM optimization loop. The agent reads metrics every 4 timesteps, reasons about building state, and adjusts HVAC setpoints.

### Full Comparison

```bash
python main.py compare
```

Runs both baseline and optimized sequentially, prints a savings summary, and generates `outputs/comparison.csv`.

### Check simulation history

```bash
python main.py status
```

---

## Dashboard

```bash
python main.py dashboard
python main.py dashboard --simulation-id optimized_abc123 --no-open-browser
```

Generates a self-contained interactive HTML dashboard at `outputs/dashboard.html` showing:
- Energy savings KPI cards
- Cumulative energy comparison (baseline vs optimized)
- Temperature timeline with comfort band
- PMV comfort index
- HVAC power usage
- Occupancy profile
- Carbon emissions
- Energy breakdown (HVAC / lighting / equipment)
- Comfort violations

---

## Reports

```bash
python main.py report                          # Markdown (default)
python main.py report --format html           # HTML with styling
python main.py report --format pdf            # PDF (requires WeasyPrint)
python main.py report --format csv            # Raw CSV export
python main.py report --simulation-id xyz --format pdf
```

Reports include:
- Executive summary (natural language)
- Energy performance table
- Comfort statistics (PMV, temperature)
- Peak demand analysis
- Recommendations

---

## MCP Server

The MCP server exposes 8 tools that the LLM uses to interact with the building:

| Tool | Description |
|------|-------------|
| `read_latest_metrics` | Get current temperature, energy, PMV, CO₂ |
| `read_energy_history` | Get historical trend data |
| `update_setpoint` | Set cooling/heating/fan setpoints |
| `modify_schedule` | Adjust occupancy schedule |
| `run_simulation_step` | Advance simulation N timesteps |
| `restart_simulation` | Reset and restart |
| `generate_dashboard` | Trigger dashboard generation |
| `save_report` | Generate a report |

To run the MCP server standalone (for integration with other MCP clients):

```bash
python main.py mcp-server
```

---

## LLM Integration

The agent uses this reasoning loop:

```
Every N timesteps:
  1. read_latest_metrics → current state
  2. read_energy_history → 1-hour trend
  3. Build prompt with:
     - Current metrics
     - Trend summary
     - Recent decisions (memory)
     - Carbon intensity
     - Electricity price (TOU)
  4. Query LLM → JSON decision
  5. validate_and_clamp → safe setpoints
  6. Apply to simulation
  7. Store decision in DB + memory
```

**System prompt key rules:**
- PMV must stay −0.5 to +0.5
- Temperature must stay 22–25°C during occupancy
- Never violate dead band (cooling ≥ heating + 2°C)
- Aggressive setback during unoccupied hours
- Respond ONLY with JSON

**Self-correction:** If the LLM returns invalid JSON or missing fields, the engine retries up to 3 times with a correction prompt.

---

## Configuration

All configuration is in `configs/`:

```yaml
# configs/simulation.yaml
simulation:
  mode: mock          # "mock" or "energyplus"
  total_hours: 168    # 1 week

hvac:
  cooling_setpoint:
    min: 18.0
    max: 28.0
    default: 24.0

comfort:
  pmv_min: -0.5
  pmv_max: 0.5
  temp_min_c: 22.0
  temp_max_c: 25.0
```

```yaml
# configs/llm.yaml
llm:
  model: llama3
  temperature: 0.2
  
decision:
  query_every_n_steps: 4    # Query LLM every 4 timesteps
  memory_size: 20           # Remember last 20 decisions
```

Override any value with environment variables (see `.env.example`).

---

## Docker

```bash
# Build and run
docker-compose up --build

# Run specific command
docker run eco-loop optimize --hours 24 --model llama3

# Full stack with Ollama
docker-compose up -d
docker-compose exec ollama ollama pull llama3
```

---

## Testing

```bash
# All tests
pytest

# Unit tests only (fast, no EnergyPlus)
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# With coverage
pytest --cov=app --cov-report=html

# Specific test
pytest tests/unit/test_validator.py -v
```

---

## Bonus Features

| Feature | Status | Description |
|---------|--------|-------------|
| Carbon-aware optimization | ✅ | Carbon intensity (gCO₂/kWh) included in LLM context |
| Dynamic electricity pricing | ✅ | TOU tariff (off-peak / mid-peak / on-peak) |
| Weather forecast integration | ✅ Config ready | `WeatherForecast` model, API key config |
| Natural language reports | ✅ | NLG executive summaries in all report formats |
| Self-correcting retries | ✅ | Up to 3 LLM retries with correction prompt |
| Decision memory | ✅ | Sliding window of last N decisions for context |
| Decision explanation log | ✅ | Full decision history with reasoning exported |

---

## Future Work

1. **Real EnergyPlus IDF**: Integrate standard ASHRAE reference buildings (SmallOffice, MediumOffice)
2. **Multi-zone control**: Extend to building with multiple thermal zones
3. **Reinforcement learning**: Replace LLM with RL agent for continuous learning
4. **Real-time weather API**: Integrate Open-Meteo for live forecast pre-conditioning
5. **Grid-interactive buildings**: Real-time carbon intensity from ElectricityMap API
6. **Fault detection**: LLM-based anomaly detection in sensor data
7. **Digital twin**: Bi-directional sync with real BMS (BACnet/Modbus)
8. **Multi-building fleet**: Scale to portfolio of buildings with centralized agent
9. **ASHRAE Guideline 36**: Implement advanced sequences of operation
10. **Natural language control**: "Make the east wing warmer" → automated setpoint change
