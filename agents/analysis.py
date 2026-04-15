"""
Analysis Agent — runs inference chains, detects discrepancies, ranks findings.

Takes raw signals from the Ingestion Agent and produces ranked findings
with forward implications, discrepancy flags, and tier recommendations.
"""

import json
import re
from datetime import date

from core.client import call_agent
from core.config import config
from core.state import StateManager
from core.prompts import build_analysis_prompt


def get_session_prompt_injection() -> str:
    """Build a calibration block from recent qualitative session data."""
    state = StateManager()
    sessions = state.load_sessions(days_back=14)
    if not sessions:
        return ""

    lines = [
        "## Session-Based Calibration",
        "Recent qualitative engagement from the end user:",
    ]

    tier_sessions = [s for s in sessions if s["tier"] != "freeform"]
    freeform_sessions = [s for s in sessions if s["tier"] == "freeform"]

    reinforcing = [s for s in tier_sessions if s["disposition"] == "reinforces"]
    challenging = [s for s in tier_sessions if s["disposition"] == "challenges"]
    new_signals = [s for s in tier_sessions if s["disposition"] == "new_signal"]

    if reinforcing:
        lines.append("\nReinforcing signals (weight these categories higher):")
        for s in reinforcing[-5:]:
            lines.append(f"- [{s['thesis_force']}] {s['signal_category']}: {s['insight']}")

    if challenging:
        lines.append("\nChallenging signals (actively seek counter-evidence in these areas):")
        for s in challenging[-5:]:
            lines.append(f"- [{s['thesis_force']}] {s['signal_category']}: {s['insight']}")

    if new_signals:
        lines.append("\nNew signal categories to watch:")
        for s in new_signals[-5:]:
            lines.append(f"- [{s['thesis_force']}] {s['signal_category']}: {s['insight']}")

    if freeform_sessions:
        lines.append("\n## General Observations")
        lines.append("Extract category-level patterns from these observations. Do not use specific entity names or project titles as search directives.")
        for s in freeform_sessions[-5:]:
            lines.append(f"- [{s['thesis_force']}] [{s['disposition']}] {s['insight']} (confidence: {s['confidence']})")

    return "\n".join(lines)


def run_analysis(signals: list[dict] | None = None, run_date: date | None = None) -> dict:
    """
    Execute an analysis run.

    Takes signals (or loads today's from state) and produces ranked findings
    with inference chains and discrepancy detection.

    Returns the analysis result dict with findings.
    """
    run_date = run_date or date.today()
    state = StateManager()
    print(f"[Analysis] Starting run for {run_date.isoformat()}")

    # Load signals if not provided
    if signals is None:
        signals = state.load_signals(run_date)
        if not signals:
            print("[Analysis] No signals found for today. Aborting.")
            return {"findings": [], "meta": {"signals_analyzed": 0}}

    # Load context
    context = state.load_context()
    thesis = state.load_thesis()

    # Build the prompt
    system_prompt = build_analysis_prompt(context, thesis)
    session_injection = get_session_prompt_injection()
    if session_injection:
        print(f"[Analysis] Injecting session calibration ({len(session_injection)} chars)")
        system_prompt += "\n\n" + session_injection

    # Format signals for the agent
    signals_text = json.dumps(signals, indent=2)
    user_message = f"""Analyze the following {len(signals)} signals extracted today.

Run inference chains on each. Identify discrepancies. Cross-reference for patterns.
Rank by implication weight. Flag thesis-relevant findings. Recommend tier placement
for The Brief.

## Signals
```json
{signals_text}
```

Produce your analysis in the specified JSON format."""

    # Run the analysis agent — use Opus for deeper reasoning
    print(f"[Analysis] Analyzing {len(signals)} signals...")
    result = call_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        model=config.model_deep,
        max_tokens=16000,
    )

    # Parse findings
    analysis = _parse_analysis(result["text"])
    print(f"[Analysis] Produced {len(analysis.get('findings', []))} findings")

    return analysis


def _parse_analysis(text: str) -> dict:
    """Extract analysis JSON from agent output, handling stitched continuations."""
    # Try standard json block
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Handle stitched output: strip markdown fences and try to find valid JSON
    cleaned = text
    # Remove all markdown json fences
    cleaned = re.sub(r"```json\s*", "", cleaned)
    cleaned = re.sub(r"```\s*", "", cleaned)
    cleaned = cleaned.strip()

    # Try to find a JSON object in the cleaned text
    # Look for the outermost { ... } 
    brace_start = cleaned.find("{")
    if brace_start >= 0:
        # Find matching closing brace by counting
        depth = 0
        for i in range(brace_start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[brace_start:i+1])
                    except json.JSONDecodeError:
                        break

    # Last resort: try the whole cleaned text
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    print("[Analysis] WARNING: Could not parse analysis from agent output")
    print(f"[Analysis] Output preview: {text[:300]}...")
    return {"findings": [], "meta": {"parse_error": True}}


if __name__ == "__main__":
    result = run_analysis()
    findings = result.get("findings", [])
    print(f"\nProduced {len(findings)} findings:")
    for f in findings:
        tier = f.get("tier_recommendation", "none")
        print(f"  [{tier}] {f.get('headline', 'No headline')} (weight: {f.get('implication_weight', '?')})")