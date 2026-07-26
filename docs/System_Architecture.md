# Eco-Loop System Architecture

This document provides a technical overview of the autonomous closed-loop control pipeline built for the Honeywell Eco-Loop Building Agents challenge. It details our integration of the EnergyPlus simulation engine with an open-source LLM cognitive engine, focusing on tool-calling architecture, prompt engineering strategies, latency management, and efficient simulation log handling.

## 1. Tool-Calling Architecture & Communication Bus
The system employs the Model Context Protocol (MCP) to standardize communication between the digital building sandbox (EnergyPlus) and the LLM brain. 
* **MCP Server Abstraction**: A lightweight, embedded MCP server (`app/mcp/server.py`) provides standardized tool-calling functions such as `read_latest_metrics` and `read_energy_history`.
* **Forward Injection Loop**: The `DecisionEngine` queries these MCP tools to gather current simulation state variables (temperature, PMV, energy usage) and then calculates optimal HVAC set-points. These set-points are returned as a validated JSON object and injected directly back into the live EnergyPlus memory instance via the `pyenergyplus` Python API binding using EnergyPlus Actuators.

## 2. Prompt Engineering Strategies
To ensure reliable, intelligent, and formatted responses from the open-source LLM, we implemented several prompt engineering paradigms:
* **Context-Aware Framing**: The `SYSTEM_PROMPT` enforces a strict persona (Autonomous Building Optimization Agent) and explicitly defines physical boundaries, comfort bounds, and economic constraints (e.g., peak demand thresholds, carbon grid intensity).
* **Self-Correction Loops**: If the LLM produces invalid JSON, halucinates fields, or suggests physically impossible set-points, the system automatically triggers a self-correction prompt (up to 3 retries) feeding the error context back to the model before falling back to safe baseline behavior.
* **Rolling Memory Injection**: The prompt dynamically injects the last 3 control decisions along with short-term historical metrics (`history_summary`) to prevent the LLM from making rapid oscillatory decisions or getting stuck in a local minima.

## 3. Prompt Latency Management
Simulating thousands of timesteps per month requires careful management of LLM inference latency.
* **Intermittent Polling**: Instead of querying the LLM on every single EnergyPlus physics timestep (which runs every 10-15 minutes of simulated time), the `DecisionEngine` evaluates the state at configurable intervals (`query_every_n_steps=4`). During the intermediate timesteps, the simulation coasts on the previously established set-points.
* **Asynchronous Design Preparedness**: The architecture allows the underlying simulation to run decoupled from the LLM network overhead, reducing overall runtime from hours to just minutes while maintaining closed-loop integrity.

## 4. Handling Lengthy Simulation Logs
EnergyPlus generates massive amounts of data over an extended simulation time horizon. Sending full logs to the LLM would immediately exceed context windows and degrade inference quality.
* **SQLite Metrics Database**: All real-time telemetry extracted from `pyenergyplus` is persisted into a lightweight local SQLite database (`app/database/repository.py`). 
* **Targeted Retrieval**: When making a decision, the MCP tools execute SQL queries to retrieve only the *latest* metrics and an aggregated summary of the *recent* window (e.g., last 16 timesteps). This prevents context bloat while providing the LLM with the exact temporal gradients (e.g., "temperature is rising rapidly") required for forward-thinking control actions.
