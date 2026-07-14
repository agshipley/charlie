"""Editorial conclusion log + content-neutral editorial gates (revival Phase 3).

Each published brief's Tier 1/2 conclusions are logged here (rolling 14-day window).
The Analysis and Brief agents read the log to build recency/dedup, force-diversity, and
inference-discipline gates on the NEXT run — directly targeting the validation-loop and
force-collapse failures surfaced by the adversary.

FIREWALL (Phase 3 constraint): this module reads and writes ONLY the pipeline's own
published brief output (data/conclusions_log.json). It never reads adversary feedback
(data/adversary/feedback.json), per-signal ratings (data/feedback.json), or Liz's
context / session files. The gates are content-neutral editorial mechanics — the entities
and forces they list are the pipeline's own recent output, never topic guidance for what
to look at next.
"""
import json
import os
from datetime import date, timedelta

from core.config import config

_LOG_PATH = config.data_dir / "conclusions_log.json"
_RETAIN_DAYS = 14
_FORCE_LABELS = {
    "supply_exhaustion": "Supply Exhaustion",
    "demand_migration": "Demand Migration",
    "discovery_bridge": "Discovery Bridge",
}


def _load() -> list:
    if not _LOG_PATH.exists():
        return []
    try:
        with open(_LOG_PATH) as f:
            return json.load(f).get("conclusions", [])
    except Exception:
        return []


def _prune(entries: list, today: date) -> list:
    cutoff = (today - timedelta(days=_RETAIN_DAYS)).isoformat()
    return [e for e in entries if str(e.get("date", "")) >= cutoff]


def recent_conclusions(today: date | None = None) -> list:
    """Tier 1/2 conclusions from the last 14 days, newest first."""
    today = today or date.today()
    entries = _prune(_load(), today)
    return sorted(entries, key=lambda e: (e.get("date", ""), e.get("tier", 9)), reverse=True)


def append_conclusions(brief: dict, run_date: date) -> None:
    """Log today's Tier 1/2 canonical conclusions (pruned to 14 days). Never raises."""
    if not brief:
        return
    entries = _prune(_load(), run_date)
    logged = 0
    for tier_num, key in ((1, "tier_1"), (2, "tier_2")):
        tier = brief.get(key)
        if not isinstance(tier, dict):
            continue
        statement = (tier.get("headline") or "").strip()
        if not statement:
            continue
        # Idempotent by (date, tier): a same-day re-run replaces rather than duplicates,
        # so force-diversity counts can't be inflated by restarts/re-runs.
        entries = [e for e in entries
                   if not (e.get("date") == run_date.isoformat() and e.get("tier") == tier_num)]
        entries.append({
            "date": run_date.isoformat(),
            "tier": tier_num,
            "statement": statement,
            "thesis_force": tier.get("thesis_force", "none"),
        })
        logged += 1
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _LOG_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump({"conclusions": entries}, f, indent=2)
        tmp.replace(_LOG_PATH)
        print(f"[Conclusions] Logged {logged} conclusion(s); {len(entries)} in 14-day window")
    except Exception as e:
        print(f"[Conclusions] Failed to write log: {e}")


def _top_tier_force_counts(entries: list) -> dict:
    counts = {}
    for e in entries:
        if e.get("tier") in (1, 2):
            f = e.get("thesis_force", "none")
            counts[f] = counts.get(f, 0) + 1
    return counts


def _conclusions_block(entries: list) -> str:
    if not entries:
        return "(No prior Tier 1/2 conclusions logged in the last 14 days.)"
    return "\n".join(
        f"- [{e.get('date')}] Tier {e.get('tier')} · force={e.get('thesis_force', 'none')} · "
        f"{e.get('statement', '')}"
        for e in entries
    )


def gates_injection(for_agent: str, today: date | None = None) -> str:
    """Content-neutral editorial gates for 'analysis' or 'brief', built ONLY from the
    conclusion log (the pipeline's own recent output)."""
    today = today or date.today()
    entries = recent_conclusions(today)
    header = (
        "## Editorial Gates — Recency, Force Diversity, and Inference Discipline\n\n"
        "These gates are content-neutral editorial mechanics computed from Charlie's OWN\n"
        "recently published Tier 1/2 conclusions. They exist to stop the pipeline from\n"
        "re-serving prior conclusions as new intelligence and from collapsing the thesis into\n"
        "a single force. They are NOT topic guidance — do not treat the entities or forces\n"
        "below as things to look for; they are what Charlie already said.\n\n"
        "### Charlie's recent Tier 1/2 conclusions (last 14 days)\n"
        f"{_conclusions_block(entries)}\n"
    )

    if for_agent == "analysis":
        return header + (
            "\n### Recency / dedup gate\n"
            "A finding that restates, re-derives, or lightly reframes any conclusion above is\n"
            "NOT new. Do not recommend such a finding for `signal` or `bullshit_flag` tier.\n"
            "Recommend an upper tier only when the finding rests on a genuinely new triggering\n"
            "event.\n\n"
            "### Inference discipline\n"
            "- **Consistency (48h):** If a finding carries a premise forward from a recent brief\n"
            "  and your current read reverses or contradicts a conclusion above from the last 48\n"
            "  hours, flag the reversal explicitly in your reasoning — do not silently switch.\n"
            "- **Multiple interpretations:** Where the evidence supports more than one reading,\n"
            "  state at least two plausible interpretations and why you chose one BEFORE\n"
            "  assigning high confidence. Do not present one interpretation as definitive when\n"
            "  others are equally supported.\n"
            "- **Contradiction surfacing:** If today's read contradicts a logged conclusion\n"
            "  above, surface the contradiction explicitly rather than quietly overwriting it.\n\n"
            "### Framing guard\n"
            "Treat corporate self-descriptions — press releases, earnings framing, executive\n"
            "quotes — as claims to be TESTED against independent signal, not as facts. A company\n"
            "describing its own capability or intent is not evidence the capability or intent is\n"
            "real.\n"
        )

    if for_agent == "brief":
        counts = _top_tier_force_counts(entries)
        force_lines = [
            "### Force-diversity gate",
            "Tier 1 and Tier 2 must NOT both carry the same `thesis_force` unless a genuinely",
            "major new event justifies it (say so inline in `generation_notes`).",
        ]
        for f, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            if f in _FORCE_LABELS and n >= 3:
                force_lines.append(
                    f"- '{_FORCE_LABELS[f]}' ({f}) has anchored an upper tier {n} times in the "
                    "last 14 days. Do NOT anchor today's Tier 1 on this force absent a major new "
                    "event; prefer a finding mapped to a different force, or leave the tier null."
                )
        return header + (
            "\n### Recency / dedup gate\n"
            "Tier 1 and Tier 2 must each rest on a genuinely NEW event or development. If a\n"
            "candidate merely restates, re-derives, or lightly reframes any conclusion above, it\n"
            "does NOT qualify for Tier 1 or Tier 2 — surface something genuinely new or leave the\n"
            "tier null. Leaving a tier null is better than re-serving a prior conclusion.\n\n"
            + "\n".join(force_lines) + "\n"
        )

    return ""


def backfill_from_briefs(days: int = 14, today: date | None = None) -> int:
    """One-time: populate the log from the last `days` of already-published briefs so the
    recency/force gates are effective immediately. Idempotent by (date, tier). Reads only
    the pipeline's own briefs — firewall-safe."""
    from core.state import StateManager
    today = today or date.today()
    state = StateManager()
    entries = _prune(_load(), today)
    seen = {(e.get("date"), e.get("tier")) for e in entries}
    added = 0
    for i in range(days + 1):
        d = date.fromordinal(today.toordinal() - i)
        brief = state.load_brief(d)
        if not brief:
            continue
        for tier_num, key in ((1, "tier_1"), (2, "tier_2")):
            if (d.isoformat(), tier_num) in seen:
                continue
            tier = brief.get(key)
            if not isinstance(tier, dict):
                continue
            statement = (tier.get("headline") or "").strip()
            if not statement:
                continue
            entries.append({"date": d.isoformat(), "tier": tier_num,
                            "statement": statement, "thesis_force": tier.get("thesis_force", "none")})
            seen.add((d.isoformat(), tier_num))
            added += 1
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "w") as f:
            json.dump({"conclusions": entries}, f, indent=2)
    except Exception as e:
        print(f"[Conclusions] Backfill write failed: {e}")
    print(f"[Conclusions] Backfill added {added} conclusion(s) from the last {days} days of briefs")
    return added


def debug_dump_prompt(agent: str, prompt: str, run_date: date) -> None:
    """When CHARLIE_DEBUG_PROMPTS is set, write the assembled prompt for inspection."""
    if not os.getenv("CHARLIE_DEBUG_PROMPTS", "").strip():
        return
    try:
        path = config.data_dir / "debug" / f"{agent}_prompt_{run_date.isoformat()}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt, encoding="utf-8")
    except Exception:
        pass
