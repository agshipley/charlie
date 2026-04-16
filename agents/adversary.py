"""
Adversary Agent — critiques the draft brief before it renders.

Shadow mode only: output appears in MD/HTML/PDF files, never on web routes.
Runs after run_brief() and before render_brief() in the daily pipeline.
"""

import json
import re
from datetime import date

from core.client import call_agent
from core.config import config
from core.state import StateManager
from core.prompts import build_adversary_prompt


def run_adversary(brief: dict, run_date: date | None = None) -> dict:
    """
    Critique today's brief before it renders.

    Takes the brief dict from run_brief(). Loads sessions and recent briefs
    for cross-reference. Runs an Opus pass with no tool use.

    Returns adversary dict. Never crashes the pipeline — returns a null_finding
    dict on any error so render_brief() always has something to work with.
    """
    run_date = run_date or date.today()
    state = StateManager()
    print(f"[Adversary] Starting review for {run_date.isoformat()}")

    try:
        # Load context for cross-referencing
        sessions = state.load_sessions(days_back=30)
        briefs = state.load_recent_briefs(days=14)

        # Build prompts
        system_prompt, user_message = build_adversary_prompt(brief, sessions, briefs)

        # Run adversary — Opus only, no tools
        print(f"[Adversary] Running critique ({len(sessions)} sessions, {len(briefs)} prior briefs)...")
        result = call_agent(
            system_prompt=system_prompt,
            user_message=user_message,
            model=config.model_deep,
            max_tokens=8096,
            max_iterations=5,
        )

        adversary = _parse_adversary(result["text"])
        adversary["run_date"] = run_date.isoformat()
        adversary.setdefault("brief_date", run_date.isoformat())

        # Save to data/adversary/YYYY-MM-DD.json
        path = state.save_adversary(adversary, run_date)
        print(f"[Adversary] Saved to {path}")

        if adversary.get("null_finding", False):
            print("[Adversary] No findings today.")
        else:
            findings = adversary.get("findings", {})
            total = sum(len(v) for v in findings.values() if isinstance(v, list))
            print(f"[Adversary] {total} finding(s) across {len([k for k, v in findings.items() if isinstance(v, list) and v])} categories")

        return adversary

    except Exception as e:
        print(f"[Adversary] ERROR: {e}. Returning null finding so pipeline continues.")
        return _null_finding(run_date)


def _null_finding(run_date: date) -> dict:
    """Return a safe null result for when the adversary fails or finds nothing."""
    return {
        "run_date": run_date.isoformat(),
        "brief_date": run_date.isoformat(),
        "findings": {
            "flattery": [],
            "pattern_exhaustion": [],
            "inference_theater": [],
            "missing_story": [],
            "comfortable_framing": [],
        },
        "summary": None,
        "null_finding": True,
    }


def _parse_adversary(text: str) -> dict:
    """Extract adversary JSON from agent output, handling stitched continuations."""
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Strip fences and try to find the outermost JSON object
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned)
    cleaned = cleaned.strip()

    brace_start = cleaned.find("{")
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[brace_start:i + 1])
                    except json.JSONDecodeError:
                        break

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    print("[Adversary] WARNING: Could not parse output from agent")
    print(f"[Adversary] Output preview: {text[:300]}...")
    return {"null_finding": True, "summary": "Parse error — could not extract JSON", "findings": {}}


if __name__ == "__main__":
    from core.state import StateManager as SM
    state = SM()
    today = date.today()
    brief = state.load_brief(today)
    if brief:
        result = run_adversary(brief, today)
        print(json.dumps(result, indent=2))
    else:
        print(f"No brief found for {today.isoformat()}")
