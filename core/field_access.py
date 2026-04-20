"""
Field Work access layer — all Field Work retrieval and citation logic lives here.

No other agent reads field artifacts directly. Import this module.
"""

import json
import os
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .config import config
from .logging import get_logger

_log = get_logger(__name__)

# ── Cap defaults (override via env vars) ────────────────────────────────────

_CAP_WEAK = int(os.getenv("FIELD_CAP_WEAK", "2"))          # 0.70-0.79, per 7 days
_CAP_MED = int(os.getenv("FIELD_CAP_MED", "4"))            # 0.80-0.89, per 7 days
_CAP_STRONG = int(os.getenv("FIELD_CAP_STRONG", "6"))      # 0.90+, per 7 days
_CAP_PER_ARTIFACT = int(os.getenv("FIELD_CAP_PER_ARTIFACT", "2"))  # any artifact, per 14 days

_CITATIONS_LOG = config.field_dir / "citations.log"


# ── Internal helpers ─────────────────────────────────────────────────────────

def _load_all_artifacts_with_content() -> list[dict]:
    """Load all field artifacts with their extracted content and acknowledgment."""
    from .state import StateManager
    state = StateManager()
    artifacts = state.list_field_artifacts()
    results = []
    for artifact in artifacts:
        aid = artifact.get("id", "")
        extracted = state.load_field_extracted(aid)
        acknowledgment = state.load_field_acknowledgment(aid)
        if extracted:
            results.append({
                "artifact": artifact,
                "extracted": extracted,
                "acknowledgment": acknowledgment,
            })
    return results


def _extract_signal_terms(signal: dict) -> str:
    """Pull key terms from a signal into a single query string."""
    parts = []
    if signal.get("headline"):
        parts.append(signal["headline"])
    entities = signal.get("entities", [])
    if isinstance(entities, list):
        parts.extend(str(e) for e in entities)
    elif isinstance(entities, str):
        parts.append(entities)
    raw_facts = signal.get("raw_facts", "")
    if isinstance(raw_facts, list):
        parts.extend(str(r) for r in raw_facts)
    elif isinstance(raw_facts, str):
        parts.append(raw_facts)
    forward = signal.get("forward_implications", "")
    if isinstance(forward, list):
        parts.extend(str(f) for f in forward)
    elif isinstance(forward, str):
        parts.append(forward)
    return " ".join(parts)


def _build_artifact_corpus(entry: dict) -> tuple[str, str]:
    """Return (full_text, headings_text) for an artifact entry."""
    extracted = entry.get("extracted", {})
    full_text = extracted.get("full_text", "")
    sections = extracted.get("sections", [])
    headings = " ".join(s.get("heading", "") for s in sections if s.get("heading"))
    return full_text, headings


def _get_framework_terms(acknowledgment: dict | None) -> list[str]:
    """Extract framework names coined by Liz from an acknowledgment."""
    if not acknowledgment:
        return []
    frameworks = acknowledgment.get("sections", {}).get("frameworks_extracted", [])
    terms = []
    for fw in frameworks:
        if isinstance(fw, dict) and fw.get("name"):
            terms.append(fw["name"])
    return terms


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokens, stripping punctuation."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _tf_idf_relevance(query: str, documents: list[str]) -> list[float]:
    """
    Compute cosine-similarity TF-IDF scores between query and documents.

    Falls back to sklearn if available, otherwise hand-rolls it.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np

        if not documents:
            return []
        corpus = [query] + documents
        vectorizer = TfidfVectorizer(stop_words="english", min_df=1)
        tfidf = vectorizer.fit_transform(corpus)
        scores = cosine_similarity(tfidf[0:1], tfidf[1:]).flatten()
        return scores.tolist()
    except ImportError:
        # Hand-rolled fallback
        return _tfidf_fallback(query, documents)


def _tfidf_fallback(query: str, documents: list[str]) -> list[float]:
    """Simple TF-IDF cosine similarity without sklearn."""
    import math

    def tf(tokens: list[str]) -> dict:
        counts: dict = defaultdict(int)
        for t in tokens:
            counts[t] += 1
        total = len(tokens) or 1
        return {k: v / total for k, v in counts.items()}

    all_docs = [query] + documents
    all_tokens = [_tokenize(d) for d in all_docs]
    # IDF
    N = len(all_tokens)
    df: dict = defaultdict(int)
    for tokens in all_tokens:
        for t in set(tokens):
            df[t] += 1
    idf = {t: math.log(N / (1 + df[t])) for t in df}

    def tfidf_vec(tokens: list[str]) -> dict:
        tfv = tf(tokens)
        return {t: tfv[t] * idf.get(t, 0) for t in tfv}

    def cosine(a: dict, b: dict) -> float:
        dot = sum(a.get(t, 0) * b.get(t, 0) for t in a)
        mag_a = math.sqrt(sum(v * v for v in a.values())) or 1e-9
        mag_b = math.sqrt(sum(v * v for v in b.values())) or 1e-9
        return dot / (mag_a * mag_b)

    query_vec = tfidf_vec(all_tokens[0])
    return [cosine(query_vec, tfidf_vec(all_tokens[i + 1])) for i in range(len(documents))]


def _extract_matched_spans(query_tokens: set[str], extracted: dict, max_spans: int = 3) -> list[str]:
    """Return up to max_spans sentences from the artifact that overlap most with query tokens."""
    full_text = extracted.get("full_text", "")
    sentences = re.split(r"(?<=[.!?])\s+", full_text)
    scored = []
    for sent in sentences:
        toks = set(_tokenize(sent))
        overlap = len(toks & query_tokens)
        if overlap > 0:
            scored.append((overlap, sent.strip()))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_spans]]


# ── Public API ────────────────────────────────────────────────────────────────

def retrieve_field_work_for_signal(signal: dict, top_k: int = 3) -> list[dict]:
    """
    Given a signal (from today's ingestion), find Field Work artifacts whose
    content is relevant.

    Returns list of {artifact, extracted, acknowledgment, relevance_score,
    matched_spans} sorted by relevance desc.
    """
    entries = _load_all_artifacts_with_content()

    _log.info(
        "field_retrieval_called",
        agent="brief",
        num_artifacts=len(entries),
        signal_id=signal.get("headline", "")[:80],
    )

    if not entries:
        return []

    query = _extract_signal_terms(signal)
    query_tokens = set(_tokenize(query))

    # Build document texts
    full_texts = []
    heading_texts = []
    for entry in entries:
        ft, ht = _build_artifact_corpus(entry)
        full_texts.append(ft)
        heading_texts.append(ht)

    # Base TF-IDF scores against full text
    base_scores = _tf_idf_relevance(query, full_texts)

    # Heading boost (headings are a smaller, denser signal)
    heading_scores = _tf_idf_relevance(query, heading_texts) if any(heading_texts) else [0.0] * len(entries)

    results = []
    for i, entry in enumerate(entries):
        score = base_scores[i]

        # +20% weight for heading overlap
        h_score = heading_scores[i] if i < len(heading_scores) else 0.0
        score = score * 0.8 + h_score * 0.2

        # +bonus for framework term matches
        framework_terms = _get_framework_terms(entry.get("acknowledgment"))
        for term in framework_terms:
            term_tokens = set(_tokenize(term))
            if term_tokens & query_tokens:
                score = min(1.0, score + 0.05)

        # Clamp to [0, 1]
        score = min(1.0, max(0.0, score))

        matched_spans = _extract_matched_spans(query_tokens, entry.get("extracted", {}))

        results.append({
            "artifact": entry["artifact"],
            "extracted": entry["extracted"],
            "acknowledgment": entry["acknowledgment"],
            "relevance_score": round(score, 4),
            "matched_spans": matched_spans,
        })

        _log.info(
            "field_citation_considered",
            artifact_id=entry["artifact"].get("id", ""),
            relevance=round(score, 4),
            signal_id=signal.get("headline", "")[:80],
        )

    results.sort(key=lambda r: -r["relevance_score"])
    return results[:top_k]


def retrieve_field_work_for_thesis_synthesis() -> list[dict]:
    """
    Return ALL Field Work artifacts sorted by upload date desc, with extracted
    content and acknowledgment. No relevance filtering.
    """
    entries = _load_all_artifacts_with_content()
    _log.info(
        "field_retrieval_called",
        agent="thesis",
        num_artifacts=len(entries),
        num_matches=len(entries),
    )
    return entries


def retrieve_field_work_for_adversary() -> list[dict]:
    """
    Return ALL Field Work artifacts for the adversary. Same shape as thesis
    retrieval.
    """
    entries = _load_all_artifacts_with_content()
    _log.info(
        "field_retrieval_called",
        agent="adversary",
        num_artifacts=len(entries),
        num_matches=len(entries),
    )
    return entries


# ── Cap enforcement ───────────────────────────────────────────────────────────

def _load_citations_log() -> list[dict]:
    """Load all citation log entries."""
    if not _CITATIONS_LOG.exists():
        return []
    entries = []
    with open(_CITATIONS_LOG, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def check_citation_caps(
    artifact_id: str,
    relevance_score: float,
    today: date,
) -> tuple[bool, str]:
    """
    Check whether a Field Work citation is allowed based on relevance tier
    and historical caps.

    Returns (allowed: bool, reason: str).
    """
    # Re-read caps at call time so env var overrides during testing work
    cap_weak = int(os.getenv("FIELD_CAP_WEAK", str(_CAP_WEAK)))
    cap_med = int(os.getenv("FIELD_CAP_MED", str(_CAP_MED)))
    cap_strong = int(os.getenv("FIELD_CAP_STRONG", str(_CAP_STRONG)))
    cap_per_artifact = int(os.getenv("FIELD_CAP_PER_ARTIFACT", str(_CAP_PER_ARTIFACT)))

    if relevance_score < 0.70:
        return False, f"relevance {relevance_score:.2f} below 0.70 threshold"

    entries = _load_citations_log()
    today_str = today.isoformat()
    window_7 = (today - timedelta(days=7)).isoformat()
    window_14 = (today - timedelta(days=14)).isoformat()

    # Per-artifact cap: any artifact, last 14 days
    artifact_count = sum(
        1 for e in entries
        if e.get("artifact_id") == artifact_id
        and e.get("brief_date", "") >= window_14
        and e.get("brief_date", "") <= today_str
    )
    if artifact_count >= cap_per_artifact:
        return False, (
            f"per-artifact cap: {artifact_count}/{cap_per_artifact} citations "
            f"for {artifact_id} in last 14 days"
        )

    # Tier caps based on relevance
    if relevance_score >= 0.90:
        tier_label = "strong (0.90+)"
        tier_cap = cap_strong
    elif relevance_score >= 0.80:
        tier_label = "medium (0.80-0.89)"
        tier_cap = cap_med
    else:
        tier_label = "weak (0.70-0.79)"
        tier_cap = cap_weak

    tier_count = sum(
        1 for e in entries
        if e.get("brief_date", "") >= window_7
        and e.get("brief_date", "") <= today_str
        and _score_tier(e.get("relevance_score", 0.0)) == _score_tier(relevance_score)
    )
    if tier_count >= tier_cap:
        return False, (
            f"tier cap: {tier_count}/{tier_cap} {tier_label} citations in last 7 days"
        )

    return True, "allowed"


def _score_tier(score: float) -> str:
    if score >= 0.90:
        return "strong"
    if score >= 0.80:
        return "medium"
    if score >= 0.70:
        return "weak"
    return "below_threshold"


# ── Citation recording ────────────────────────────────────────────────────────

def record_citation(
    artifact_id: str,
    brief_date: date,
    signal_id: str,
    relevance_score: float,
) -> None:
    """Append a citation event to data/field/citations.log (JSONL)."""
    entry = {
        "event": "citation",
        "artifact_id": artifact_id,
        "brief_date": brief_date.isoformat(),
        "signal_id": signal_id,
        "relevance_score": round(relevance_score, 4),
    }
    _CITATIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_CITATIONS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    _log.info(
        "field_citation_allowed",
        artifact_id=artifact_id,
        relevance=round(relevance_score, 4),
        signal_id=signal_id,
        brief_date=brief_date.isoformat(),
    )


def record_suppression(
    artifact_id: str,
    brief_date: date,
    signal_id: str,
    relevance_score: float,
    reason: str,
) -> None:
    """Log a cap-suppressed citation attempt at WARN level."""
    _log.warning(
        "field_citation_suppressed",
        artifact_id=artifact_id,
        relevance=round(relevance_score, 4),
        signal_id=signal_id,
        brief_date=brief_date.isoformat(),
        reason=reason,
    )
