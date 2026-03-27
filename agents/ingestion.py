"""
Ingestion Agent — monitors entertainment industry sources and extracts signals.

Runs daily. Uses web search to scan narrative and data sources, then extracts
structured signal objects that feed the analysis pipeline.
"""

import json
import re
from datetime import date

from core.client import call_agent
from core.config import config
from core.state import StateManager
from core.prompts import build_ingestion_prompt


WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}


def run_ingestion(run_date: date | None = None) -> list[dict]:
    """
    Execute an ingestion run.

    Searches entertainment industry sources for signals, extracts structured
    signal objects, and saves them to persistent state.

    Returns the list of extracted signals.
    """
    run_date = run_date or date.today()
    state = StateManager()
    print(f"[Ingestion] Starting run for {run_date.isoformat()}")

    # Load current watchlist and thesis for context
    watchlist = state.load_watchlist()
    thesis = state.load_thesis()
    thesis_summary = thesis.get("core_argument") if thesis else None

    # Build the prompt
    system_prompt = build_ingestion_prompt(watchlist, thesis_summary)

    # The user message that kicks off the search
    user_message = f"""Today is {run_date.strftime('%B %d, %Y')}.

Run a comprehensive scan of entertainment industry sources for signals. Search for:

1. Recent news from Deadline, Variety, THR, The Wrap, Puck about deals, investments,
   hiring, departures, restructuring, and mandate shifts in the last 24-48 hours.

2. Any developments related to audio/podcast companies expanding into TV/film,
   creator economy shifts, or platform strategy changes.

3. Any discrepancies between what companies are saying publicly and what the data
   (viewership, spending, hiring patterns) suggests.

4. Anything touching the active watchlist entities.

Search broadly. Extract every signal you find. Do not pre-filter for relevance —
that is the Analysis Agent's job. Return your findings as the specified JSON format."""

    # Run the agent with web search
    print("[Ingestion] Running search agent...")
    result = call_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        tools=[WEB_SEARCH_TOOL],
        model=config.model_daily,
    )

    # Parse signals from agent output
    signals = _parse_signals(result["text"])
    print(f"[Ingestion] Extracted {len(signals)} signals")

    # Save to state
    if signals:
        path = state.save_signals(signals, run_date)
        print(f"[Ingestion] Saved signals to {path}")

    return signals


def _parse_signals(text: str) -> list[dict]:
    """Extract JSON signal array from agent output text."""
    # Try to find JSON block in the text
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to parse the whole text as JSON
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
