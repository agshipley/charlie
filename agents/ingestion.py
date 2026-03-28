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

SYSTEM_SEARCH = """You are a news researcher. Search for the requested topic and return a concise summary of what you find. Include specific names, companies, numbers, dates, and URLs. Be factual, not interpretive."""

SYSTEM_STRUCTURE = """You are a signal extractor for an entertainment industry intelligence system.

You will receive raw search results from multiple research passes. Your job is to extract structured signals — events with forward implications that go beyond what is explicitly stated.

For each signal, return a JSON object with:
- "headline": one-sentence signal description (not a news headline)
- "source": publication name
- "source_url": URL if available
- "signal_type": one of investment, hiring, departure, deal, viewership, mandate_shift, partnership, restructuring, earnings, other
- "entities": list of companies/people involved
- "raw_facts": concrete verifiable facts
- "forward_implications": list of logical implications
- "thesis_relevance": how this relates to entertainment industry restructuring and creator ecosystem democratization (null if not relevant)
- "confidence": high, medium, or low
- "implication_weight": 1-10

Filter out routine coverage (premieres, casting, release dates) unless they carry structural implications. Return a JSON array in ```json``` blocks."""


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
            "name": "Industry data signals",
            "query": f"Search for recent entertainment industry data: streaming viewership numbers, box office performance, studio earnings, show order rates, or hiring/layoff announcements at major studios and platforms. Today is {today}.",
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

    # Structuring pass — no web search, just extraction
    combined = "\n\n---\n\n".join(raw_results)
    print(f"[Ingestion] Structuring {len(raw_results)} result sets into signals...")

    structure_result = call_agent(
        system_prompt=SYSTEM_STRUCTURE,
        user_message=f"Extract structured signals from the following research results gathered on {today}:\n\n{combined}",
        model=config.model_daily,
        max_iterations=3,
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