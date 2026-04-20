"""
Oven Agent — generates on-demand strategic takes for Liz.

Takes are focused strategic syntheses grounded in the current thesis,
recent briefs, and Field Work documents.
"""

import json
import uuid
from datetime import datetime

from core.client import call_agent
from core.config import config
from core.state import StateManager
from core.prompts import build_oven_prompt
from core.logging import get_logger

_log = get_logger(__name__)
_state = StateManager()


def run_oven(prompt: str, take_id: str | None = None) -> dict:
    """
    Generate a take for the given prompt.

    Returns the full take record (saved to disk) or raises on failure.
    """
    take_id = take_id or f"take_{uuid.uuid4().hex[:12]}"
    _log.info("oven_started", take_id=take_id, prompt_length=len(prompt))

    # ── Load context ─────────────────────────────────────────────────────
    thesis = _state.load_thesis()
    recent_briefs = _state.load_recent_briefs(days=14)
    context = _state.load_context()
    recent_sessions = _state.load_sessions(days_back=7)

    # ── Load Field Work with extracted content ───────────────────────────
    artifacts = _state.list_field_artifacts()
    field_artifacts = []
    for a in artifacts:
        extracted = _state.load_field_extracted(a["id"])
        ack_raw = _state.load_field_artifact(a["id"])
        entry = dict(a)
        entry["extracted_content"] = extracted or {}
        entry["acknowledgment"] = (ack_raw or {}).get("acknowledgment") or {}
        field_artifacts.append(entry)

    _log.info("oven_context_loaded",
              take_id=take_id,
              briefs=len(recent_briefs),
              field_artifacts=len(field_artifacts),
              sessions=len(recent_sessions))

    # ── Build prompt ─────────────────────────────────────────────────────
    system_prompt, user_message = build_oven_prompt(
        user_prompt=prompt,
        thesis=thesis,
        recent_briefs=recent_briefs,
        field_artifacts=field_artifacts,
        context=context,
        recent_sessions=recent_sessions,
    )

    # ── Call model ───────────────────────────────────────────────────────
    result = call_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        model=config.model_deep,
        max_tokens=8096,
    )

    raw_text = result.get("text", "")
    _log.info("oven_response_received", take_id=take_id, response_length=len(raw_text))

    # ── Parse JSON ───────────────────────────────────────────────────────
    take_data = _parse_take(raw_text)

    # ── Save ─────────────────────────────────────────────────────────────
    record = {
        "take_id": take_id,
        "generated_at": datetime.now().isoformat(),
        "prompt": prompt,
        "take": take_data,
    }
    path = _state.save_take(record)
    _log.info("oven_take_saved", take_id=take_id, path=str(path))

    return record


def _parse_take(raw_text: str) -> dict:
    """Extract JSON take object from model response."""
    text = raw_text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` block
    import re
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    _log.warning("oven_parse_failed", raw_length=len(raw_text))
    return {
        "situation": "Parse error — raw response below.",
        "whats_on_their_mind": "",
        "worth_raising": [],
        "watch_for": [],
        "open_loops": [],
        "generation_notes": raw_text[:500],
    }
