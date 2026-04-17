"""
Acknowledgment Agent — Charlie's first-read response to a Field Work artifact.

Reads the extracted document content + current thesis. Produces a structured
five-section acknowledgment: what the document argues, frameworks extracted,
empirical foundation, thesis connections, open questions.

Model: Opus (config.model_deep). Single call, no tool use.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from core.client import call_agent
from core.config import config
from core.logging import get_logger
from core.prompts import build_acknowledge_prompt
from core.state import StateManager

_log = get_logger(__name__)
_FAILED_PLACEHOLDER = "Acknowledgment generation failed — retry from the detail page."


def run_acknowledge(artifact: dict) -> dict:
    """
    Generate Charlie's first-read acknowledgment of a Field artifact.

    Reads: artifact dict, extracted content from
    data/field/extracted/{artifact_id}.json, current thesis.

    Does NOT read: Liz's context files (profile/slate/watching),
    feedback.json, sessions.json.

    Returns the acknowledgment dict. Saves to
    data/field/acknowledgments/{artifact_id}.json.
    Raises on failure after saving a minimal failed record.
    """
    artifact_id = artifact["id"]
    state = StateManager()
    bound = _log.bind(artifact_id=artifact_id)
    bound.info("acknowledgment_start")
    _start = time.monotonic()

    # Load extracted content
    extracted = state.load_field_extracted(artifact_id)
    if not extracted:
        raise ValueError(f"No extracted content found for {artifact_id}")

    # Load thesis
    thesis = state.load_thesis() or {}

    # Build prompts
    system_prompt, user_message = build_acknowledge_prompt(artifact, extracted, thesis)

    word_count_read = extracted.get("word_count", 0)
    bound.info(
        "acknowledgment_opus_call",
        word_count_read=word_count_read,
        model=config.model_deep,
    )

    try:
        result = call_agent(
            system_prompt=system_prompt,
            user_message=user_message,
            model=config.model_deep,
            max_tokens=8096,
            max_iterations=1,  # single call, no tool use
        )
    except Exception as exc:
        duration = round(time.monotonic() - _start, 2)
        bound.error("acknowledgment_failed", duration_seconds=duration, exc_info=True)
        ack = _failed_ack(artifact_id, str(exc), word_count_read, duration)
        _save_ack(state, artifact_id, ack)
        raise

    duration = round(time.monotonic() - _start, 2)
    raw_text = result.get("text", "")

    try:
        ack = _parse_acknowledgment(raw_text)
    except Exception as exc:
        bound.error("acknowledgment_parse_failed", duration_seconds=duration, exc_info=True)
        ack = _failed_ack(artifact_id, f"JSON parse failed: {exc}", word_count_read, duration)
        _save_ack(state, artifact_id, ack)
        raise ValueError(f"Acknowledgment JSON parse failed: {exc}") from exc

    # Stamp generation metadata
    ack["artifact_id"] = artifact_id
    ack["generated_at"] = datetime.now(timezone.utc).isoformat()
    ack.setdefault("generation_notes", {})
    ack["generation_notes"]["word_count_read"] = word_count_read
    ack["generation_notes"]["duration_seconds"] = duration
    ack["generation_notes"]["model"] = config.model_deep

    _save_ack(state, artifact_id, ack)

    bound.info(
        "acknowledgment_complete",
        duration_seconds=duration,
        sections=list(ack.get("sections", {}).keys()),
    )
    return ack


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_acknowledgment(text: str) -> dict:
    """Extract and parse JSON from the model response."""
    # Strip markdown code fences if present
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        text = m.group(1).strip()

    data = json.loads(text)

    # Validate required sections exist
    sections = data.get("sections", {})
    required = [
        "what_i_read_this_to_be_arguing",
        "frameworks_extracted",
        "empirical_foundation",
        "connections_to_current_thesis",
        "open_questions",
    ]
    for key in required:
        if key not in sections:
            raise ValueError(f"Missing required section: {key}")

    return data


def _failed_ack(artifact_id: str, error: str, word_count_read: int, duration: float) -> dict:
    """Minimal acknowledgment record for failed generation."""
    return {
        "artifact_id": artifact_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "failed": True,
        "error_message": error,
        "sections": {
            "what_i_read_this_to_be_arguing": _FAILED_PLACEHOLDER,
            "frameworks_extracted": [],
            "empirical_foundation": _FAILED_PLACEHOLDER,
            "connections_to_current_thesis": [],
            "open_questions": [],
        },
        "generation_notes": {
            "word_count_read": word_count_read,
            "duration_seconds": duration,
            "model": config.model_deep,
        },
    }


def _save_ack(state: StateManager, artifact_id: str, ack: dict) -> Path:
    """Save acknowledgment to data/field/acknowledgments/{artifact_id}.json."""
    path = config.field_dir / "acknowledgments" / f"{artifact_id}.json"
    state._atomic_write_json(path, ack)
    return path


def load_acknowledgment(artifact_id: str) -> dict | None:
    """Load acknowledgment for a given artifact. Returns None if not found."""
    path = config.field_dir / "acknowledgments" / f"{artifact_id}.json"
    if path.exists():
        import json as _json
        with open(path) as f:
            return _json.load(f)
    return None
