"""
Thesis Synthesizer — accumulates signals and proposes thesis updates.

Runs on a longer cadence (weekly). Reviews accumulated signals, cross-references
against the current thesis, and produces update proposals for Andrew to review.
"""

import json
import re
from datetime import date

from core.client import call_agent
from core.config import config
from core.state import StateManager
from core.prompts import build_thesis_prompt


def run_thesis(days_back: int = 7) -> dict:
    """
    Execute a thesis synthesis run.

    Reviews signals from the last N days, cross-references against the current
    thesis, and produces an update proposal.

    Returns the proposal dict.
    """
    state = StateManager()
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

    if not recent_signals and not thesis:
        print("[Thesis] No signals and no existing thesis. Nothing to synthesize.")
        return {}

    # Build the prompt
    system_prompt = build_thesis_prompt(thesis, recent_signals)

    user_message = f"""Review the {len(recent_signals)} signals from the past {days_back} days
against the current thesis state.

Produce a thesis update proposal following the specified format. Be specific about
what should be extended, what should be revised, and what new patterns are emerging.

Every proposed change must cite specific signals as evidence.

If this is the initial thesis, propose a structured starting framework based on
the available signals and the thesis subject description in your instructions."""

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
        print("[Thesis] ⚠️  Proposal requires Andrew's review before application.")

    return proposal


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
