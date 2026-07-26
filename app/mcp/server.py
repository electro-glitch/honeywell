"""
MCP Server for Eco-Loop Building Agents
=========================================
Exposes 8 building optimization tools via the Model Context Protocol.
The server runs over stdio transport and is used by the LLM agent.

Usage:
    python -m app.mcp.server   # stdio mode (for LLM)
    python -m app.mcp.server --sse  # SSE mode (for web clients)
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types as mcp_types
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning("MCP SDK not installed; server will run in passthrough mode")

from app.mcp import tools as t


def create_mcp_app() -> Any:
    """Create and configure the MCP server application."""
    if not MCP_AVAILABLE:
        logger.warning("MCP not available; returning stub server")
        return None

    server = Server("eco-loop-building-agents")

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name="read_latest_metrics",
                description=(
                    "Read the most recent building performance metrics for a simulation. "
                    "Returns indoor temperature, humidity, PMV, energy use, CO₂, and cost."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "simulation_id": {
                            "type": "string",
                            "description": "The simulation run identifier",
                        }
                    },
                    "required": ["simulation_id"],
                },
            ),
            mcp_types.Tool(
                name="read_energy_history",
                description=(
                    "Read historical energy and comfort data for trend analysis. "
                    "Returns a list of timestep snapshots."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "simulation_id": {"type": "string"},
                        "last_n": {
                            "type": "integer",
                            "description": "Number of recent timesteps to return (default 96)",
                            "default": 96,
                        },
                    },
                    "required": ["simulation_id"],
                },
            ),
            mcp_types.Tool(
                name="update_setpoint",
                description=(
                    "Update HVAC setpoints for the running simulation. "
                    "Provide cooling setpoint (°C), heating setpoint (°C), and fan speed (0–1). "
                    "Changes apply at the next simulation timestep."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "simulation_id": {"type": "string"},
                        "cooling_setpoint": {
                            "type": "number",
                            "minimum": 15.0,
                            "maximum": 35.0,
                        },
                        "heating_setpoint": {
                            "type": "number",
                            "minimum": 10.0,
                            "maximum": 30.0,
                        },
                        "fan_speed": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "simulation_id",
                        "cooling_setpoint",
                        "heating_setpoint",
                        "fan_speed",
                    ],
                },
            ),
            mcp_types.Tool(
                name="modify_schedule",
                description=(
                    "Modify the occupancy schedule for a specific hour of day. "
                    "Affects internal gains and ventilation requirements."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "simulation_id": {"type": "string"},
                        "hour": {"type": "integer", "minimum": 0, "maximum": 23},
                        "occupancy_fraction": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                    "required": ["simulation_id", "hour", "occupancy_fraction"],
                },
            ),
            mcp_types.Tool(
                name="run_simulation_step",
                description="Advance the simulation by a given number of timesteps.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "simulation_id": {"type": "string"},
                        "steps": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 1,
                        },
                    },
                    "required": ["simulation_id"],
                },
            ),
            mcp_types.Tool(
                name="restart_simulation",
                description="Stop and restart a simulation from the beginning.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "simulation_id": {"type": "string"},
                        "mode": {
                            "type": "string",
                            "enum": ["mock", "energyplus"],
                            "default": "energyplus",
                        },
                    },
                    "required": ["simulation_id"],
                },
            ),
            mcp_types.Tool(
                name="generate_dashboard",
                description=(
                    "Generate an interactive Plotly HTML dashboard for a simulation. "
                    "Returns the path to the generated HTML file."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "simulation_id": {"type": "string"},
                        "output_path": {
                            "type": "string",
                            "default": "outputs/dashboard.html",
                        },
                    },
                    "required": ["simulation_id"],
                },
            ),
            mcp_types.Tool(
                name="save_report",
                description=(
                    "Generate and save a simulation performance report. "
                    "Supported formats: 'markdown', 'html', 'pdf', 'csv'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "simulation_id": {"type": "string"},
                        "format": {
                            "type": "string",
                            "enum": ["markdown", "html", "pdf", "csv"],
                            "default": "markdown",
                        },
                        "output_path": {"type": "string"},
                    },
                    "required": ["simulation_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[mcp_types.TextContent]:
        logger.info(f"MCP call_tool: {name}({json.dumps(arguments, indent=2)})")

        result = _dispatch_tool(name, arguments)

        return [mcp_types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def _dispatch_tool(name: str, arguments: dict) -> dict:
    """Route tool call to implementation function."""
    dispatch: dict[str, Any] = {
        "read_latest_metrics": lambda a: t.read_latest_metrics(
            simulation_id=a["simulation_id"]
        ),
        "read_energy_history": lambda a: t.read_energy_history(
            simulation_id=a["simulation_id"],
            last_n=a.get("last_n", 96),
        ),
        "update_setpoint": lambda a: t.update_setpoint(
            simulation_id=a["simulation_id"],
            cooling_setpoint=a["cooling_setpoint"],
            heating_setpoint=a["heating_setpoint"],
            fan_speed=a["fan_speed"],
            reason=a.get("reason", "LLM decision"),
        ),
        "modify_schedule": lambda a: t.modify_schedule(
            simulation_id=a["simulation_id"],
            hour=a["hour"],
            occupancy_fraction=a["occupancy_fraction"],
        ),
        "run_simulation_step": lambda a: t.run_simulation_step(
            simulation_id=a["simulation_id"],
            steps=a.get("steps", 1),
        ),
        "restart_simulation": lambda a: t.restart_simulation(
            simulation_id=a["simulation_id"],
            mode=a.get("mode", "energyplus"),
        ),
        "generate_dashboard": lambda a: t.generate_dashboard(
            simulation_id=a["simulation_id"],
            output_path=a.get("output_path", "outputs/dashboard.html"),
        ),
        "save_report": lambda a: t.save_report(
            simulation_id=a["simulation_id"],
            format=a.get("format", "markdown"),
            output_path=a.get("output_path"),
        ),
    }

    fn = dispatch.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}

    try:
        return fn(arguments)
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        return {"error": str(e), "tool": name}


# ── Direct call interface (used by LLM client without MCP protocol) ──────────

def call_tool_direct(name: str, arguments: dict) -> dict:
    """
    Call an MCP tool directly (bypasses MCP protocol overhead).
    Used by the LLM agent when running in-process.
    """
    return _dispatch_tool(name, arguments)


async def run_server_stdio() -> None:
    """Run the MCP server in stdio mode."""
    if not MCP_AVAILABLE:
        raise RuntimeError("MCP SDK not installed. Run: pip install mcp")

    server = create_mcp_app()
    async with stdio_server() as (read_stream, write_stream):
        logger.info("Eco-Loop MCP Server running on stdio")
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_server_stdio())
