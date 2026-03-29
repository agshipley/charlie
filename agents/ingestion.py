"""
Ingestion Agent — monitors entertainment industry sources and extracts signals.

Runs daily. Makes multiple small, focused API calls with web search, each scoped
to a specific search domain. Then a final structuring call (no web search) combines
the raw results into structured signal objects.

This architecture avoids the timeout problem caused by accumulating too many
search results in a single API call's context window.
"""

import json
import re
from datetime import date

from core.client import call_agent
from core.config import config
from core.state import StateManager


WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 3,
}

SYSTEM_SEARCH = """You are a news researcher. Search for the requested topic and return a concise summary of what you find. Include specific names, companies, numbers, dates, and URLs. Be factual, not interpretive.

CRITICAL: For each item you report, include the publication date. Prioritize stories published in the last 48 hours. If a story is older than one week, only include it if it contains genuinely new data or developments not previously reported."""

SYSTEM_STRUCTURE = """You are a signal extractor for an entertainment industry intelligence system.

You will receive raw search results from multiple research passes. Extract structured signals — events with forward implications beyond what is explicitly stated.

## Thesis Framework
Tag each signal with which force it relates to:
1. SUPPLY EXHAUSTION: Traditional IP pipelines (books, comics, games, songs, theater, journalism, life rights, toys) showing saturation.
2. DEMAND MIGRATION: Audiences pulled to creator platforms by algorithmic discovery. Streamers lack equivalent targeting.
3. DISCOVERY BRIDGE: Creator-branded content as the mechanism for bringing audiences back to scripted.

For each signal, return a JSON object with:
- "headline": one-sentence signal description
- "source": publication name
- "source_url": URL if available
- "signal_type": one of investment, hiring, departure, deal, viewership, mandate_shift, partnership, restructuring, earnings, ip_saturation, audience_migration, exec_move, other
- "entities": list of companies/people involved
- "raw_facts": concrete verifiable facts
- "forward_implications": list of logical implications
- "thesis_force": supply_exhaustion, demand_migration, discovery_bridge, or none
- "thesis_relevance": how this relates to the thesis (null if not relevant)
- "confidence": high, medium, or low
- "implication_weight": 1-10
- "event_date": the date the underlying event actually occurred (not the article date), as precise as possible
- "is_new": true if the event occurred in the last 48 hours, false if older

RECENCY RULES: Only include signals where the underlying event occurred in the last 48 hours OR where genuinely new data/developments have emerged about an older event. Do not repackage old news with new framing. If a story is a new article about an old event with no new information, exclude it.

Filter out routine coverage unless it carries structural implications. Return a JSON array in ```json``` blocks."""


def run_ingestion(run_date: date | None = None) -> list[dict]:
    """
    Execute an ingestion run using multiple focused search passes.
    """
    run_date = run_date or date.today()
    state = StateManager()
    today = run_date.strftime("%B %d, %Y")
    print(f"[Ingestion] Starting run for {run_date.isoformat()}")

    # Load watchlist for targeted searches
    watchlist = state.load_watchlist()
    watchlist_companies = watchlist.get("companies", [])

    # Define search passes — each is a separate, small API call
    search_passes = [
        {
            "name": "Trades scan",
            "query": f"Search Deadline, Variety, and The Hollywood Reporter for the most important entertainment industry news from {today}. Focus on deals, investments, hiring, departures, restructuring, and strategic moves. Summarize each story with key facts.",
        },
        {
            "name": "Creator/audio expansion",
            "query": f"Search for recent news about podcast companies expanding into TV or film, creator economy developments, video podcasting moves by Netflix or other platforms, and audio-to-scripted adaptation deals. Include any news about Audiochuck, Wondery, Spotify, or iHeartMedia in entertainment. Today is {today}.",
        },
        {
            "name": "Watchlist entities",
            "query": f"Search for recent news about these specific companies and people: {', '.join(watchlist_companies[:8])}. Focus on strategic moves, investments, hiring, partnerships, or restructuring. Today is {today}.",
        },
        {
            "name": "IP pipeline and audience data",
            "query": f"Search for recent entertainment industry data: streaming viewership numbers, box office performance, video game adaptation deals, book-to-screen option activity, comic book adaptation performance, music catalog licensing for film/TV, audience migration between platforms, ad-supported streaming tier growth. Today is {today}.",
        },
        {
            "name": "Structural analysis",
            "query": f"Search for recent analysis from Matthew Ball, Richard Rushfield Ankler, Matthew Belloni Puck, or Parrot Analytics about entertainment industry restructuring, streaming economics, creator economy, or content strategy shifts. Today is {today}.",
        },
    ]

    # Execute each search pass
    raw_results = []
    for i, search_pass in enumerate(search_passes, 1):
        name = search_pass["name"]
        print(f"[Ingestion] Pass {i}/{len(search_passes)}: {name}")

        result = call_agent(
            system_prompt=SYSTEM_SEARCH,
            user_message=search_pass["query"],
            tools=[WEB_SEARCH_TOOL],
            model=config.model_daily,
            max_iterations=5,
        )

        text = result["text"].strip()
        if text:
            raw_results.append(f"## {name}\n\n{text}")
            print(f"[Ingestion]   ✓ Got results ({len(text)} chars)")
        else:
            print(f"[Ingestion]   ✗ No results")

    if not raw_results:
        print("[Ingestion] No results from any search pass.")
        return []

    # Load feedback calibration
    feedback_injection = ""
    try:
        from web import get_feedback_prompt_injection
        feedback_injection = get_feedback_prompt_injection()
        if feedback_injection:
            print(f"[Ingestion] Injecting feedback calibration ({len(feedback_injection)} chars)")
    except ImportError:
        pass

    # Structuring pass — no web search, just extraction
    combined = "\n\n---\n\n".join(raw_results)
    system_with_feedback = SYSTEM_STRUCTURE
    if feedback_injection:
        system_with_feedback += "\n\n" + feedback_injection
    print(f"[Ingestion] Structuring {len(raw_results)} result sets into signals...")

    structure_result = call_agent(
        system_prompt=system_with_feedback,
        user_message=f"Extract structured signals from the following research results gathered on {today}:\n\n{combined}",
        model=config.model_daily,
        max_tokens=16000,
        max_iterations=5,
    )

    # Parse signals
    signals = _parse_signals(structure_result["text"])
    print(f"[Ingestion] Extracted {len(signals)} signals")

    # Save
    if signals:
        path = state.save_signals(signals, run_date)
        print(f"[Ingestion] Saved to {path}")

    return signals


def _parse_signals(text: str) -> list[dict]:
    """Extract JSON signal array from agent output text."""
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    print("[Ingestion] WARNING: Could not parse signals from agent output")
    return []


if __name__ == "__main__":
    signals = run_ingestion()
    print(f"\nExtracted {len(signals)} signals:")
    for s in signals:
        print(f"  - [{s.get('signal_type', '?')}] {s.get('headline', 'No headline')}")