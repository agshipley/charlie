"""
Thesis Synthesizer — accumulates signals and proposes thesis updates.

Runs on a longer cadence (weekly). Reviews accumulated signals, cross-references
against the current thesis, and produces update proposals for Andrew to review.
"""

import json
import re
from datetime import date, datetime

from core.client import call_agent
from core.config import config
from core.logging import get_logger
from core.state import StateManager
from core.prompts import build_thesis_prompt
import core.field_access as field_access

_log = get_logger(__name__)


def run_thesis(days_back: int = 7) -> dict:
    """
    Execute a thesis synthesis run.

    Reviews signals from the last N days, cross-references against the current
    thesis, and produces an update proposal.

    Returns the proposal dict.
    """
    import time
    state = StateManager()
    _log.info("agent_start", agent="thesis", days_back=days_back)
    _start = time.monotonic()
    print(f"[Thesis] Starting synthesis run (last {days_back} days)")

    # Load current thesis
    thesis = state.load_thesis()
    if thesis:
        print(f"[Thesis] Current thesis last updated: {thesis.get('updated_at', 'unknown')}")
    else:
        print("[Thesis] No existing thesis found. Will propose initial version.")

    # Load recent signals
    recent_signals = state.load_recent_signals(days=days_back)
    print(f"[Thesis] Loaded {len(recent_signals)} signals from last {days_back} days")

    # Load recent session data
    sessions = state.load_sessions(days_back=days_back)
    print(f"[Thesis] Loaded {len(sessions)} session entries from last {days_back} days")

    if not recent_signals and not thesis:
        print("[Thesis] No signals and no existing thesis. Nothing to synthesize.")
        _log.info("agent_complete", agent="thesis", days_back=days_back,
                  proposal_generated=False, duration_seconds=round(time.monotonic() - _start, 2))
        return {}

    # Load Field Work corpus
    field_work = field_access.retrieve_field_work_for_thesis_synthesis()
    print(f"[Thesis] Loaded {len(field_work)} Field Work artifact(s) for synthesis")

    # Build the prompt
    system_prompt = build_thesis_prompt(thesis, recent_signals, field_work=field_work)

    # Build session block for user message
    session_block = ""
    if sessions:
        tier_sessions = [s for s in sessions if s["tier"] != "freeform"]
        freeform_sessions = [s for s in sessions if s["tier"] == "freeform"]

        session_lines = [
            "\n## User Engagement Signals (This Week)",
            "The following insights emerged from the end user's engagement with daily briefs.",
            'Treat "challenges" dispositions as high-priority investigation targets.',
            'Treat "new_signal" dispositions as potential thesis extensions.',
        ]
        for s in tier_sessions:
            session_lines.append(
                f"- [{s['disposition'].upper()}] [{s['thesis_force']}] {s['signal_category']}: {s['insight']} (confidence: {s['confidence']})"
            )
        if freeform_sessions:
            session_lines.append("\nGeneral observations (extract category-level patterns only):")
            for s in freeform_sessions:
                session_lines.append(
                    f"- [{s['disposition'].upper()}] [{s['thesis_force']}] {s['insight']} (confidence: {s['confidence']})"
                )
        session_block = "\n".join(session_lines)

    user_message = f"""Review the {len(recent_signals)} signals from the past {days_back} days
against the current thesis state.

Produce a thesis update proposal following the specified format. Be specific about
what should be extended, what should be revised, and what new patterns are emerging.

Every proposed change must cite specific signals as evidence.

If this is the initial thesis, propose a structured starting framework based on
the available signals and the thesis subject description in your instructions.{session_block}"""

    # Use Opus for deep reasoning
    print("[Thesis] Running synthesis...")
    result = call_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        model=config.model_deep,
    )

    # Parse the proposal
    proposal = _parse_proposal(result["text"])

    if proposal:
        # Save as a proposal for review (not directly applied)
        path = state.save_thesis_proposal(proposal)
        print(f"[Thesis] Proposal saved to {path}")
        print(f"[Thesis] Summary: {proposal.get('summary', 'No summary')}")
        print(f"[Thesis] Extensions proposed: {len(proposal.get('extensions', []))}")
        print(f"[Thesis] Revisions proposed: {len(proposal.get('revisions', []))}")
        print(f"[Thesis] New patterns identified: {len(proposal.get('new_patterns', []))}")
        fw_engagements = proposal.get("field_work_engagements", [])
        print(f"[Thesis] Field Work engagements: {len(fw_engagements)}")
        print("[Thesis] ⚠️  Proposal requires Andrew's review before application.")
        _log.info(
            "field_thesis_engagement",
            proposal_date=date.today().isoformat(),
            num_engagements=len(fw_engagements),
        )
        _log.info("agent_complete", agent="thesis", days_back=days_back,
                  proposal_generated=True,
                  extensions=len(proposal.get("extensions", [])),
                  revisions=len(proposal.get("revisions", [])),
                  new_patterns=len(proposal.get("new_patterns", [])),
                  field_work_engagements=len(fw_engagements),
                  duration_seconds=round(time.monotonic() - _start, 2))
    else:
        _log.info("agent_complete", agent="thesis", days_back=days_back,
                  proposal_generated=False, duration_seconds=round(time.monotonic() - _start, 2))

    return proposal


def refine_proposal(proposal: dict, thesis: dict) -> dict:
    """
    Run an Opus refinement pass on a proposal using Liz's annotations.

    Takes the current proposal (with flags and annotations), the current thesis
    state, and produces a revised proposal incorporating feedback.
    """
    annotated_items = []
    for key in ("extensions", "revisions", "new_patterns"):
        for item in proposal.get(key, []):
            if item.get("annotation") or item.get("flag"):
                annotated_items.append({
                    "section": key,
                    "id": item["id"],
                    "flag": item.get("flag"),
                    "annotation": item.get("annotation", ""),
                    "current_content": item,
                })

    if not annotated_items:
        return proposal

    system_prompt = f"""You are the thesis synthesizer for Charlie, an entertainment
industry intelligence system. You are refining a thesis update proposal based on
editorial feedback from the domain expert (Liz Varner).

Current thesis state:
{json.dumps(thesis, indent=2)}

Your job:
- Items flagged "accept": keep as-is
- Items flagged "needs_revision": revise based on the annotation
- Items flagged "reject": remove from the proposal
- Items with annotations but no flag: use the annotation to improve the item
- Preserve item IDs across revisions so the reviewer can track changes
- Do not introduce new items unless an annotation specifically requests one
- Maintain the same JSON structure as the input proposal

Respond with the complete revised proposal as a JSON block."""

    user_message = f"""Here is the current proposal (iteration {proposal['iteration']}):
{json.dumps(proposal, indent=2)}

The reviewer provided the following feedback:
{json.dumps(annotated_items, indent=2)}

Produce the revised proposal incorporating this feedback. Return valid JSON only."""

    print(f"[Thesis] Refining proposal (iteration {proposal['iteration']})...")
    result = call_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        model=config.model_deep,
    )

    revised = _parse_proposal(result["text"])

    if revised:
        revised["iteration"] = proposal["iteration"] + 1
        revised["max_iterations"] = proposal.get("max_iterations", 5)
        revised["status"] = "in_review"
        revised["history"] = proposal.get("history", []) + [{
            "iteration": revised["iteration"],
            "type": "refinement",
            "timestamp": datetime.now().isoformat(),
            "annotations_count": len(annotated_items),
        }]
        for key in ("extensions", "revisions", "new_patterns"):
            for item in revised.get(key, []):
                item.setdefault("flag", None)
                item.setdefault("annotation", None)
        return revised

    return proposal


def publish_proposal(proposal: dict) -> bool:
    """
    Apply a reviewed proposal to current.json.

    Items flagged 'reject' or 'needs_revision' are skipped.
    Everything else is applied.
    """
    state = StateManager()
    current_thesis = state.load_thesis()

    if not current_thesis:
        print("[Thesis] No existing thesis to update.")
        return False

    applied = {"extensions": 0, "revisions": 0, "new_patterns": 0}

    for ext in proposal.get("extensions", []):
        if ext.get("flag") not in ("reject", "needs_revision"):
            current_thesis.setdefault("claims", []).append({
                "claim": ext["claim"],
                "confidence": ext.get("confidence", "medium"),
                "force": ext.get("force", "general"),
            })
            applied["extensions"] += 1

    for rev in proposal.get("revisions", []):
        if rev.get("flag") not in ("reject", "needs_revision"):
            claim_id = rev.get("claim_id")
            claims = current_thesis.get("claims", [])
            if claim_id is not None and claim_id < len(claims):
                claims[claim_id]["claim"] = rev["revised_claim"]
                if rev.get("confidence"):
                    claims[claim_id]["confidence"] = rev["confidence"]
                applied["revisions"] += 1

    for pat in proposal.get("new_patterns", []):
        if pat.get("flag") not in ("reject", "needs_revision"):
            force_key = pat.get("suggested_force", "discovery_bridge")
            force = current_thesis.get("forces", {}).get(force_key, {})
            force.setdefault("evidence", []).append(pat["pattern"])
            applied["new_patterns"] += 1

    current_thesis["version"] = current_thesis.get("version", 0) + 1
    current_thesis["updated_at"] = datetime.now().isoformat()

    state.save_thesis(current_thesis)
    print(f"[Thesis] Published: {applied['extensions']} extensions, "
          f"{applied['revisions']} revisions, {applied['new_patterns']} new patterns")
    return True


def apply_proposal(proposal_path: str):
    """
    Apply a reviewed and approved thesis proposal.

    This should only be called after Andrew has reviewed the proposal.
    """
    state = StateManager()

    with open(proposal_path, "r") as f:
        proposal = json.load(f)

    if proposal.get("status") != "approved":
        print("[Thesis] Proposal has not been approved. Set status to 'approved' first.")
        return

    current_thesis = state.load_thesis() or {
        "core_argument": "",
        "claims": [],
        "evidence": [],
    }

    # Apply extensions
    for extension in proposal.get("extensions", []):
        current_thesis["claims"].append(extension)

    # Apply revisions
    for revision in proposal.get("revisions", []):
        claim_id = revision.get("claim_id")
        if claim_id is not None and claim_id < len(current_thesis["claims"]):
            current_thesis["claims"][claim_id] = revision.get("revised_claim", current_thesis["claims"][claim_id])

    # Add new evidence
    for evidence in proposal.get("evidence_cited", []):
        current_thesis["evidence"].append(evidence)

    # Save updated thesis
    state.save_thesis(current_thesis)
    print("[Thesis] ✓ Thesis updated successfully.")


def _parse_proposal(text: str) -> dict:
    """Extract proposal JSON from agent output."""
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

    print("[Thesis] WARNING: Could not parse proposal from agent output")
    return {}


if __name__ == "__main__":
    proposal = run_thesis()
    if proposal:
        print(f"\nProposal summary: {proposal.get('summary', 'No summary')}")
    else:
        print("No proposal generated.")
