"""
Data Parser Utilities
======================
Helper functions for parsing, normalizing, and validating
building data from various sources.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

import pandas as pd
from loguru import logger


def parse_energyplus_output(raw: dict) -> dict:
    """
    Normalize raw EnergyPlus API output to standard metric keys.
    Maps EnergyPlus internal variable names to Eco-Loop names.
    """
    mapping = {
        "Zone Air Temperature": "indoor_temp_c",
        "Site Outdoor Air Drybulb Temperature": "outdoor_temp_c",
        "Zone Air Relative Humidity": "humidity_pct",
        "Zone Air CO2 Concentration": "co2_ppm",
        "Zone People Occupant Count": "occupant_count",
        "Facility Total HVAC Electric Energy": "hvac_electricity_j",
        "Facility Total Building Electric Demand Power": "total_electric_power_w",
    }

    normalized = {}
    for ep_key, eco_key in mapping.items():
        if ep_key in raw:
            value = raw[ep_key]
            # Convert Joules to kWh where needed
            if eco_key.endswith("_j"):
                normalized[eco_key.replace("_j", "_kwh")] = value / 3_600_000
            else:
                normalized[eco_key] = value

    return normalized


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_llm_decision(text: str) -> Optional[dict]:
    """
    Attempt to parse a JSON control decision from LLM text output.
    Handles markdown code blocks and partial JSON.
    """
    # Strip code fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    # Try direct parse
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    # Try to extract first JSON object
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to parse LLM decision from: {text[:100]}")
    return None


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize a metrics DataFrame:
    - Parse timestamp column
    - Forward-fill missing values
    - Round float columns
    """
    if df.empty:
        return df

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    float_cols = df.select_dtypes(include="float64").columns
    df[float_cols] = df[float_cols].round(4)

    df = df.ffill()

    return df


def compute_hourly_aggregates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate per-timestep data to hourly summaries.
    """
    if df.empty:
        return df

    if "timestamp" not in df.columns:
        return df

    df = df.copy()
    df["hour"] = pd.to_datetime(df["timestamp"]).dt.floor("h")

    agg = df.groupby("hour").agg(
        total_energy_kwh=("total_electricity_kwh", "sum"),
        avg_temp_c=("indoor_temp_c", "mean"),
        avg_pmv=("pmv", "mean"),
        avg_occupancy=("occupancy_fraction", "mean"),
        total_carbon_kg=("carbon_kg_co2", "sum"),
        total_cost=("electricity_cost", "sum"),
        hvac_energy_kwh=("hvac_electricity_kwh", "sum"),
        peak_hvac_kw=("hvac_power_kw", "max"),
    ).reset_index()

    return agg
