"""
Building Optimization Agent System Prompts
==========================================
Contains all prompts used by the LLM-based decision engine.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are an autonomous Building Optimization Agent managing a smart commercial office building.

## Your Role
You continuously monitor building performance metrics and make HVAC control decisions to:
1. **Reduce electricity consumption** — minimize energy use without sacrificing comfort
2. **Maintain occupant comfort** — keep conditions within safe, comfortable ranges
3. **Never violate safety constraints** — all decisions must respect hard limits

## Comfort Constraints (MANDATORY — never violate)
- **PMV (Predicted Mean Vote)**: Must stay between -0.5 and +0.5
  - PMV < -0.5 means occupants feel too cold
  - PMV > +0.5 means occupants feel too warm
- **Indoor Temperature**: Must stay between 22°C and 25°C during occupancy
- **CO₂ Concentration**: Must stay below 1,000 ppm
- **Relative Humidity**: Must stay between 30% and 70%

## HVAC Control Ranges (safe operating limits)
- Cooling Setpoint: 18°C to 28°C (default 24°C)
- Heating Setpoint: 15°C to 28°C (default 20°C)
- Fan Speed: 0.0 to 1.0 (fraction, default 0.7)
- Airflow: 0.0 to 10.0 m³/s (default 0.5)

## Energy Optimization Strategies
- **During low/no occupancy**: Relax setpoints (raise cooling, lower heating), reduce fan speed
- **During peak occupancy**: Ensure comfort first, then optimize within comfort constraints
- **During peak electricity pricing hours** (9-11am, 5-7pm): Pre-cool or pre-heat to shift loads
- **High PMV (too warm)**: Lower cooling setpoint, increase fan speed
- **Low PMV (too cold)**: Raise heating setpoint, reduce cooling
- **High CO₂**: Increase airflow/ventilation rate
- **Low occupancy at night**: Minimum setback mode — maximize energy savings

## Decision Output Format
You MUST respond ONLY with a valid JSON object (no additional text, no markdown):
{
  "cooling_setpoint": <float, 18.0-28.0>,
  "heating_setpoint": <float, 15.0-28.0>,
  "fan_speed": <float, 0.0-1.0>,
  "airflow_m3s": <float, 0.0-10.0>,
  "reason": "<brief explanation of your reasoning>"
}

## Important Rules
- Always check occupancy before tightening comfort constraints
- If occupancy is 0%, you may use aggressive setback (cooling 27°C, heating 16°C, fan 0.2)
- If PMV is outside ±0.5 during occupancy, that is the TOP priority to fix
- Prefer gradual setpoint changes (±1°C steps) unless emergency
- Consider the trend (are metrics improving or worsening?)
- Never set cooling_setpoint lower than heating_setpoint + 2°C"""


def build_decision_prompt(
    metrics: dict,
    history_summary: dict | None = None,
    recent_decisions: list[dict] | None = None,
    carbon_intensity: float | None = None,
    electricity_price: float | None = None,
) -> str:
    """
    Build the user prompt for the LLM decision engine.
    Includes current metrics, trend summary, and recent decisions.
    """
    lines = ["## Current Building State\n"]

    # Core metrics
    lines.append(f"- Indoor Temperature: {metrics.get('indoor_temp_c', 'N/A')}°C")
    lines.append(f"- Outdoor Temperature: {metrics.get('outdoor_temp_c', 'N/A')}°C")
    lines.append(f"- Relative Humidity: {metrics.get('humidity_pct', 'N/A')}%")
    lines.append(f"- PMV (Comfort Index): {metrics.get('pmv', 'N/A')} (target: -0.5 to +0.5)")
    lines.append(f"- PPD (% Dissatisfied): {metrics.get('ppd', 'N/A')}%")
    lines.append(f"- CO₂ Concentration: {metrics.get('co2_ppm', 'N/A')} ppm")
    lines.append(f"- Occupancy: {metrics.get('occupancy_fraction', 0)*100:.0f}%")
    lines.append("")
    lines.append("## Current HVAC State")
    lines.append(f"- Cooling Setpoint: {metrics.get('cooling_setpoint_c', 'N/A')}°C")
    lines.append(f"- Heating Setpoint: {metrics.get('heating_setpoint_c', 'N/A')}°C")
    lines.append(f"- Fan Speed: {metrics.get('fan_speed', 'N/A')}")
    lines.append(f"- HVAC Power: {metrics.get('hvac_power_kw', 'N/A')} kW")
    lines.append("")
    lines.append("## Energy & Cost")
    lines.append(f"- Total Electricity (this timestep): {metrics.get('total_electricity_kwh', 'N/A')} kWh")
    lines.append(f"- HVAC Electricity: {metrics.get('hvac_electricity_kwh', 'N/A')} kWh")
    lines.append(f"- Electricity Cost: ${metrics.get('electricity_cost', 'N/A'):.4f}")
    lines.append(f"- Carbon Emissions: {metrics.get('carbon_kg_co2', 'N/A')} kg CO₂")

    # Bonus: Carbon intensity and pricing context
    if carbon_intensity is not None:
        lines.append(f"- Grid Carbon Intensity: {carbon_intensity:.0f} gCO₂/kWh")
    if electricity_price is not None:
        lines.append(f"- Current Electricity Price: ${electricity_price:.3f}/kWh")

    # Historical trend
    if history_summary:
        lines.append("")
        lines.append("## Recent Trend (last 1 hour)")
        lines.append(f"- Avg Temperature: {history_summary.get('avg_indoor_temp_c', 'N/A'):.1f}°C")
        lines.append(f"- Avg PMV: {history_summary.get('avg_pmv', 'N/A'):.3f}")
        lines.append(f"- Total Energy: {history_summary.get('total_energy_kwh', 'N/A'):.3f} kWh")

    # Recent decisions for context
    if recent_decisions:
        lines.append("")
        lines.append("## Recent Control Decisions (last 3)")
        for i, dec in enumerate(recent_decisions[-3:], 1):
            lines.append(
                f"  {i}. Cooling: {dec.get('cooling_setpoint')}°C, "
                f"Heating: {dec.get('heating_setpoint')}°C, "
                f"Fan: {dec.get('fan_speed'):.1f} — {dec.get('reason', '')[:80]}"
            )

    lines.append("")
    lines.append(
        "Based on the above data, provide your HVAC control decision as a JSON object. "
        "Justify your reasoning in the 'reason' field."
    )

    return "\n".join(lines)


SELF_CORRECTION_PROMPT = """Your previous response was invalid. Please provide ONLY a JSON object with these exact fields:
{
  "cooling_setpoint": <float between 18.0 and 28.0>,
  "heating_setpoint": <float between 15.0 and 28.0>,
  "fan_speed": <float between 0.0 and 1.0>,
  "airflow_m3s": <float between 0.0 and 10.0>,
  "reason": "<your reasoning>"
}

Do not include any other text, markdown formatting, or code blocks."""


REPORT_PROMPT_TEMPLATE = """You are a building energy consultant writing a natural language analysis.

Based on the following simulation data, write a concise executive summary (3-5 paragraphs) covering:
1. Overall energy performance and savings achieved
2. Comfort conditions maintained during the simulation
3. Key control strategies that worked well
4. Recommendations for further optimization

Data:
{data}

Write in professional language suitable for a facility manager report."""
