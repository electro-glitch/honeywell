"""
SQLite database connection and schema management.

Uses aiosqlite for async I/O and synchronous sqlite3 for sync contexts.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import aiosqlite
from loguru import logger

from app.config import get_config

# ── DDL ─────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS simulation_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id   TEXT NOT NULL UNIQUE,
    mode            TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    total_timesteps INTEGER DEFAULT 0,
    total_energy_kwh REAL DEFAULT 0.0,
    total_cost      REAL DEFAULT 0.0,
    total_carbon_kg REAL DEFAULT 0.0,
    avg_pmv         REAL DEFAULT 0.0,
    comfort_violations INTEGER DEFAULT 0,
    llm_model       TEXT,
    config_snapshot TEXT
);

CREATE TABLE IF NOT EXISTS building_metrics (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id           TEXT NOT NULL,
    mode                    TEXT NOT NULL,
    timestep                INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    indoor_temp_c           REAL NOT NULL,
    outdoor_temp_c          REAL NOT NULL,
    heating_setpoint_c      REAL DEFAULT 20.0,
    cooling_setpoint_c      REAL DEFAULT 24.0,
    humidity_pct            REAL DEFAULT 50.0,
    pmv                     REAL DEFAULT 0.0,
    ppd                     REAL DEFAULT 5.0,
    hvac_electricity_kwh    REAL DEFAULT 0.0,
    lighting_electricity_kwh REAL DEFAULT 0.0,
    equipment_electricity_kwh REAL DEFAULT 0.0,
    total_electricity_kwh   REAL DEFAULT 0.0,
    occupancy_fraction      REAL DEFAULT 0.0,
    occupant_count          INTEGER DEFAULT 0,
    co2_ppm                 REAL DEFAULT 400.0,
    hvac_power_kw           REAL DEFAULT 0.0,
    fan_speed               REAL DEFAULT 0.7,
    airflow_m3s             REAL DEFAULT 0.5,
    carbon_kg_co2           REAL DEFAULT 0.0,
    electricity_price_per_kwh REAL DEFAULT 0.10,
    electricity_cost        REAL DEFAULT 0.0,
    FOREIGN KEY (simulation_id) REFERENCES simulation_runs(simulation_id)
);

CREATE TABLE IF NOT EXISTS control_decisions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id           TEXT NOT NULL,
    timestep                INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    cooling_setpoint        REAL NOT NULL,
    heating_setpoint        REAL NOT NULL,
    fan_speed               REAL NOT NULL,
    airflow_m3s             REAL,
    reason                  TEXT NOT NULL,
    llm_model               TEXT DEFAULT 'llama3',
    raw_response            TEXT,
    was_validated           INTEGER DEFAULT 1,
    validation_notes        TEXT,
    carbon_intensity_g_kwh  REAL,
    electricity_price_per_kwh REAL,
    FOREIGN KEY (simulation_id) REFERENCES simulation_runs(simulation_id)
);

CREATE TABLE IF NOT EXISTS comfort_violations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id   TEXT NOT NULL,
    timestep        INTEGER NOT NULL,
    timestamp       TEXT NOT NULL,
    violation_type  TEXT NOT NULL,
    actual_value    REAL NOT NULL,
    limit_value     REAL NOT NULL,
    severity        REAL DEFAULT 0.0,
    FOREIGN KEY (simulation_id) REFERENCES simulation_runs(simulation_id)
);

CREATE INDEX IF NOT EXISTS idx_metrics_sim_id ON building_metrics(simulation_id);
CREATE INDEX IF NOT EXISTS idx_metrics_timestep ON building_metrics(timestep);
CREATE INDEX IF NOT EXISTS idx_decisions_sim_id ON control_decisions(simulation_id);
CREATE INDEX IF NOT EXISTS idx_violations_sim_id ON comfort_violations(simulation_id);
"""


def get_db_path() -> Path:
    cfg = get_config()
    return cfg.resolve(cfg.database.path)


def init_db(db_path: Path | None = None) -> None:
    """Initialise SQLite schema synchronously (call once at startup)."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(DDL)
        conn.commit()
    logger.info(f"Database initialised at {path}")


@contextmanager
def get_sync_db(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for synchronous SQLite access."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@asynccontextmanager
async def get_async_db(
    db_path: Path | None = None,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Async context manager for aiosqlite access."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(path)) as conn:
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
