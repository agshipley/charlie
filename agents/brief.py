"""
Brief Generator — produces The Morning Loaf's three-tier output.

Takes ranked findings from the Analysis Agent and Liz's persistent context,
generates the daily Brief: Signal, Bullshit Flag, Your World.
"""

import json
import re
from datetime import date

from core.client import call_agent
from core.config import config
from core.logging import get_logger
from core.state import StateManager
from core.prompts import build_brief_prompt
import core.field_access as field_access

_log = get_logger(__name__)


def run_brief(findings: dict | None = None, run_date: date | None = None) -> dict:
    """
    Generate The Morning Loaf from analysis findings.

    Returns the brief dict with tier_1, tier_2, tier_3.
    """
    import time
    run_date = run_date or date.today()
    state = StateManager()
    _log.info("agent_start", agent="brief", run_date=run_date.isoformat())
    _start = time.monotonic()
    print(f"[Brief] Starting generation for {run_date.isoformat()}")

    # Load context
    context = state.load_context()

    # Format findings for the agent
    if findings is None:
        print("[Brief] No findings provided. Cannot generate brief.")
        _log.info("agent_complete", agent="brief", run_date=run_date.isoformat(),
                  tiers=0, duration_seconds=round(time.monotonic() - _start, 2))
        return {}

    # ── Field Work retrieval for tier-three candidates ────────────────────
    field_work_context = None
    best_candidate = None
    tier3_candidates = [
        f for f in findings.get("findings", [])
        if f.get("tier_recommendation") == "your_world"
    ]
    if tier3_candidates:
        # Use the highest-weight candidate as the representative signal
        best_candidate = max(tier3_candidates, key=lambda f: f.get("implication_weight", 0))
        fw_results = field_access.retrieve_field_work_for_signal(best_candidate, top_k=3)
        if fw_results:
            top = fw_results[0]
            relevance = top["relevance_score"]
            artifact_id = top["artifact"]["id"]
            allowed, reason = field_access.check_citation_caps(artifact_id, relevance, run_date)
            if allowed:
                field_work_context = top
                print(f"[Brief] Field Work citation allowed: {artifact_id} (relevance={relevance:.2f})")
            else:
                field_access.record_suppression(
                    artifact_id=artifact_id,
                    brief_date=run_date,
                    signal_id=best_candidate.get("headline", "")[:80],
                    relevance_score=relevance,
                    reason=reason,
                )
                print(f"[Brief] Field Work citation suppressed: {reason}")

    # Build the prompt (field_work_context may be None)
    system_prompt = build_brief_prompt(context, field_work_context=field_work_context)

    findings_text = json.dumps(findings, indent=2)
    user_message = f"""Generate today's Brief from the following analysis findings.

## Analysis Output
```json
{findings_text}
```

Select the highest-impact items for each tier. Remember:
- Tier 1 (The Signal): highest-implication finding, not biggest headline
- Tier 2 (The Bullshit Flag): only fires if a genuine discrepancy exists
- Tier 3 (Your World): only fires if something directly touches Liz's world

If a tier doesn't have a qualifying item, leave it null. Never pad.

Produce the Brief in the specified JSON format."""

    print("[Brief] Generating...")
    result = call_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        model=config.model_daily,
    )

    # Parse the brief
    brief = _parse_brief(result["text"])

    # Save
    if brief:
        path = state.save_brief(brief, run_date)
        print(f"[Brief] Saved to {path}")
        # Record citation now that the brief is saved
        if field_work_context:
            field_access.record_citation(
                artifact_id=field_work_context["artifact"]["id"],
                brief_date=run_date,
                signal_id=best_candidate.get("headline", "")[:80],
                relevance_score=field_work_context["relevance_score"],
            )

    # Print the brief for visibility
    _print_brief(brief)

    tiers = sum(1 for k in ("tier_1", "tier_2", "tier_3") if brief.get(k))
    _log.info("agent_complete", agent="brief", run_date=run_date.isoformat(),
              tiers=tiers, duration_seconds=round(time.monotonic() - _start, 2))
    return brief


def _parse_brief(text: str) -> dict:
    """Extract brief JSON from agent output."""
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    print("[Brief] WARNING: Could not parse brief from agent output")
    return {}


def _print_brief(brief: dict):
    """Print the brief in a readable format."""
    if not brief:
        print("[Brief] No brief generated.")
        return

    print("\n" + "=" * 60)
    print(f"  THE BRIEF — {brief.get('date', 'today')}")
    print("=" * 60)

    tier1 = brief.get("tier_1")
    if tier1:
        print(f"\n  THE SIGNAL")
        print(f"  {tier1.get('headline', '')}")
        print(f"  {tier1.get('body', '')}")
        print(f"  → {tier1.get('open_question', '')}")

    tier2 = brief.get("tier_2")
    if tier2:
        print(f"\n  THE BULLSHIT FLAG")
        print(f"  {tier2.get('headline', '')}")
        print(f"  {tier2.get('body', '')}")
        print(f"  → {tier2.get('open_question', '')}")
    else:
        print(f"\n  THE BULLSHIT FLAG: [nothing worth flagging today]")

    tier3 = brief.get("tier_3")
    if tier3:
        print(f"\n  YOUR WORLD")
        print(f"  {tier3.get('headline', '')}")
        print(f"  {tier3.get('body', '')}")
        print(f"  → {tier3.get('open_question', '')}")
    else:
        print(f"\n  YOUR WORLD: [nothing directly touching your slate today]")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    # For testing — load today's signals, analyze, and generate brief
    from agents.analysis import run_analysis
    analysis = run_analysis()
    if analysis.get("findings"):
        run_brief(analysis)
    else:
        print("No findings to generate a brief from.")
