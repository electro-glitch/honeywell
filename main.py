"""
Eco-Loop Building Agents — Main CLI
=====================================
Typer-based command-line interface.

Commands:
  baseline   — Run EnergyPlus with default setpoints (no LLM)
  optimize   — Run LLM-driven HVAC optimization
  compare    — Run both and produce comparison report
  dashboard  — Generate interactive HTML dashboard
  report     — Generate simulation report (md/html/pdf/csv)
  status     — Show simulation run history
  mcp-server — Start the MCP server in stdio mode

Usage:
  python main.py baseline --hours 168
  python main.py optimize --model qwen2.5
  python main.py compare
  python main.py dashboard --simulation-id optimized_abc123
  python main.py report --simulation-id optimized_abc123 --format pdf
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Ensure the project root is in the path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import get_config
from app.logging_config import setup_logging

app = typer.Typer(
    name="eco-loop",
    help="🏢 Eco-Loop Building Agents — Autonomous AI Building Optimization",
    rich_markup_mode="rich",
    pretty_exceptions_enable=True,
)
console = Console()


def _init(log_level: str = "INFO") -> None:
    """Common initialization: logging and output dirs."""
    cfg = get_config()
    setup_logging(level=log_level, log_file=cfg.logging.file)
    cfg.ensure_output_dirs()


# ── baseline ─────────────────────────────────────────────────────────────────


@app.command()
def baseline(
    hours: int = typer.Option(168, help="Simulation duration in hours (168 = 1 week)"),
    mode: str = typer.Option("energyplus", help="Simulation backend: 'mock' or 'energyplus'"),
    log_level: str = typer.Option("INFO", help="Log level: DEBUG|INFO|WARNING|ERROR"),
) -> None:
    """
    [bold blue]Run baseline simulation[/bold blue] with fixed HVAC setpoints (no LLM).

    Stores results to SQLite and exports baseline.csv.
    """
    _init(log_level)

    from app.config import get_config

    cfg = get_config()
    cfg.simulation.mode = mode
    cfg.simulation.total_hours = hours

    console.print(
        Panel(
            f"[bold]Mode:[/bold] Baseline (no LLM)\n"
            f"[bold]Backend:[/bold] {mode}\n"
            f"[bold]Duration:[/bold] {hours} hours ({hours * cfg.simulation.timesteps_per_hour} timesteps)",
            title="Eco-Loop -- Baseline",
            border_style="blue",
        )
    )

    from app.controllers.control_loop import OptimizationLoop

    loop = OptimizationLoop(mode="baseline", config=cfg)
    sim_id = loop.run()

    console.print(f"\n[green]OK: Baseline complete. Simulation ID: {sim_id}[/green]")
    console.print(f"[dim]Results: {cfg.output.baseline_csv}[/dim]")


# ── optimize ──────────────────────────────────────────────────────────────────


@app.command()
def optimize(
    hours: int = typer.Option(168, help="Simulation duration in hours"),
    mode: str = typer.Option("energyplus", help="Simulation backend: 'mock' or 'energyplus'"),
    model: str = typer.Option("", help="LLM model name (e.g. llama3, mistral, qwen2.5)"),
    log_level: str = typer.Option("INFO", help="Log level"),
    simulation_id: str | None = typer.Option(None, help="Custom simulation ID"),
) -> None:
    """
    [bold green]Run LLM-driven HVAC optimization[/bold green].

    The AI agent reads metrics via MCP tools and adjusts setpoints at every
    query interval. Requires Ollama (or falls back to rule-based stub).
    """
    _init(log_level)

    from app.config import get_config

    cfg = get_config()
    cfg.simulation.mode = mode
    cfg.simulation.total_hours = hours
    if model:
        cfg.llm.model = model

    console.print(
        Panel(
            f"[bold]Mode:[/bold] LLM Optimization\n"
            f"[bold]Backend:[/bold] {mode}\n"
            f"[bold]LLM Model:[/bold] {cfg.llm.model}\n"
            f"[bold]Duration:[/bold] {hours} hours\n"
            f"[bold]Query Interval:[/bold] every {cfg.llm.query_every_n_steps} timestep(s)",
            title="Eco-Loop -- Optimize",
            border_style="green",
        )
    )

    from app.controllers.control_loop import OptimizationLoop

    loop = OptimizationLoop(mode="optimized", simulation_id=simulation_id, config=cfg)
    sim_id = loop.run()

    console.print(f"\n[green]OK: Optimization complete. Simulation ID: {sim_id}[/green]")
    console.print(f"[dim]Results: {cfg.output.optimized_csv}[/dim]")


# ── compare ───────────────────────────────────────────────────────────────────


@app.command()
def compare(
    hours: int = typer.Option(168, help="Simulation duration for both runs"),
    mode: str = typer.Option("energyplus", help="Simulation backend"),
    model: str = typer.Option("", help="LLM model for optimization run"),
    log_level: str = typer.Option("INFO", help="Log level"),
) -> None:
    """
    [bold cyan]Run baseline + optimization sequentially[/bold cyan] and compare results.

    Generates comparison.csv and shows savings summary.
    """
    _init(log_level)

    from app.config import get_config

    cfg = get_config()
    cfg.simulation.mode = mode
    cfg.simulation.total_hours = hours
    if model:
        cfg.llm.model = model

    console.print(
        Panel(
            f"Running full comparison:\n"
            f"  1. Baseline ({hours}h, {mode})\n"
            f"  2. Optimized ({hours}h, {mode}, LLM: {cfg.llm.model})",
            title="Eco-Loop -- Compare",
            border_style="cyan",
        )
    )

    from app.controllers.control_loop import run_comparison

    baseline_id, optimized_id = run_comparison(cfg)

    console.print("\n[green]OK: Comparison complete.[/green]")
    console.print(f"Baseline ID:  {baseline_id}")
    console.print(f"Optimized ID: {optimized_id}")


# ── dashboard ─────────────────────────────────────────────────────────────────


@app.command()
def dashboard(
    simulation_id: str | None = typer.Option(None, help="Simulation ID to visualize"),
    baseline_id: str | None = typer.Option(None, help="Baseline simulation ID"),
    output: str = typer.Option("outputs/dashboard.html", help="Output HTML file path"),
    open_browser: bool = typer.Option(True, help="Auto-open browser after generation"),
    log_level: str = typer.Option("INFO", help="Log level"),
) -> None:
    """
    [bold yellow]Generate interactive Plotly dashboard[/bold yellow].

    If no simulation_id is given, uses the most recent simulation in the database.
    """
    _init(log_level)

    from app.database.repository import list_simulation_runs

    all_runs = list_simulation_runs()
    if not all_runs:
        console.print(
            "[red]No simulations found in database. Run 'baseline' or 'optimize' first.[/red]"
        )
        raise typer.Exit(1)

    # Smart-resolve: find the best-matching optimized + baseline pair
    if simulation_id is None:
        # Default: pick most recent optimized; pair with closest-step baseline
        opt_runs = [r for r in all_runs if r.mode == "optimized" and r.total_timesteps > 0]
        base_runs = [r for r in all_runs if r.mode == "baseline" and r.total_timesteps > 0]
        if opt_runs:
            opt_run = opt_runs[0]  # most recent optimized
            simulation_id = opt_run.simulation_id
            if not baseline_id and base_runs:
                # Pick baseline with highest energy — true unoptimised baseline always uses most power
                valid_bases = [r for r in base_runs if r.total_energy_kwh > 0]
                if valid_bases:
                    best_base = max(valid_bases, key=lambda r: r.total_energy_kwh)
                else:
                    best_base = min(
                        base_runs, key=lambda r: abs(r.total_timesteps - opt_run.total_timesteps)
                    )
                baseline_id = best_base.simulation_id
        else:
            # Fall back to most recent run of any mode
            simulation_id = all_runs[0].simulation_id

    console.print(f"Using most recent simulation: [cyan]{simulation_id}[/cyan]")
    if baseline_id:
        console.print(f"Pairing with baseline:        [cyan]{baseline_id}[/cyan]")

    console.print(f"Generating dashboard for: [cyan]{simulation_id}[/cyan]")

    from app.dashboard.dashboard import generate_dashboard as _gen

    out_path = _gen(
        simulation_id=simulation_id,
        baseline_id=baseline_id,
        output_path=output,
        auto_open=open_browser,
    )

    console.print(f"\n[green]OK: Dashboard generated: {out_path}[/green]")


# ── report ────────────────────────────────────────────────────────────────────


@app.command()
def report(
    simulation_id: str | None = typer.Option(None, help="Simulation ID"),
    format: str = typer.Option("markdown", help="Output format: markdown|html|pdf|csv"),
    output: str | None = typer.Option(None, help="Output file path override"),
    log_level: str = typer.Option("INFO", help="Log level"),
) -> None:
    """
    [bold magenta]Generate simulation report[/bold magenta] in the specified format.

    Formats: markdown, html, pdf, csv
    """
    _init(log_level)

    from app.database.repository import list_simulation_runs

    if simulation_id is None:
        all_runs = list_simulation_runs()
        if not all_runs:
            console.print("[red]No simulations found. Run a simulation first.[/red]")
            raise typer.Exit(1)
        simulation_id = all_runs[0].simulation_id
        console.print(f"Using simulation: [cyan]{simulation_id}[/cyan]")

    console.print(f"Generating [magenta]{format}[/magenta] report…")

    from app.dashboard.reporter import generate_report

    out_path = generate_report(simulation_id=simulation_id, fmt=format, output_path=output)

    console.print(f"\n[green]OK: Report saved: {out_path}[/green]")


# ── status ────────────────────────────────────────────────────────────────────


@app.command()
def status(
    limit: int = typer.Option(10, help="Number of recent runs to show"),
) -> None:
    """
    [bold]Show simulation run history[/bold] from the database.
    """
    _init()

    from app.database.repository import list_simulation_runs

    runs = list_simulation_runs()[:limit]

    if not runs:
        console.print("[yellow]No simulation runs found in database.[/yellow]")
        return

    table = Table(title="Simulation History", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Mode", style="green")
    table.add_column("Started")
    table.add_column("Steps", justify="right")
    table.add_column("Energy (kWh)", justify="right")
    table.add_column("Cost ($)", justify="right")
    table.add_column("PMV avg", justify="right")
    table.add_column("Violations", justify="right", style="yellow")
    table.add_column("LLM")

    for run in runs:
        table.add_row(
            run.simulation_id[:12] + "…",
            run.mode,
            run.started_at.strftime("%m-%d %H:%M"),
            str(run.total_timesteps),
            f"{run.total_energy_kwh:.2f}",
            f"{run.total_cost:.2f}",
            f"{run.avg_pmv:.3f}",
            str(run.comfort_violations),
            run.llm_model or "—",
        )

    console.print(table)


# ── mcp-server ────────────────────────────────────────────────────────────────


@app.command("mcp-server")
def mcp_server() -> None:
    """
    [bold]Start the MCP server[/bold] in stdio mode for LLM tool use.

    Used when integrating with an external LLM client via the MCP protocol.
    """
    import asyncio

    _init()
    console.print("[cyan]Starting Eco-Loop MCP Server (stdio)…[/cyan]")
    from app.mcp.server import run_server_stdio

    asyncio.run(run_server_stdio())


# ── Main entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
