"""
Charlie Orchestrator — coordinates agent execution on scheduled cadences.

This is the main entry point. When run, it determines which agents need to
execute based on the current schedule and runs them in sequence.

Daily pipeline: Ingestion → Analysis → Brief
Weekly pipeline: Thesis Synthesis (produces proposal for review)

Usage:
    python orchestrator.py              # Run the daily pipeline
    python orchestrator.py --full       # Run daily + thesis synthesis
    python orchestrator.py --thesis     # Run thesis synthesis only
    python orchestrator.py --test       # Dry run with verbose output
"""

import argparse
import sys
from datetime import date, datetime

from core.config import config
from agents.ingestion import run_ingestion
from agents.analysis import run_analysis
from agents.brief import run_brief
from agents.thesis import run_thesis


def run_daily_pipeline(run_date: date | None = None):
    """Execute the daily pipeline: Ingestion → Analysis → Brief."""
    run_date = run_date or date.today()
    print(f"\n{'='*60}")
    print(f"  CHARLIE — Daily Pipeline")
    print(f"  {run_date.strftime('%A, %B %d, %Y')}")
    print(f"  Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

    # Step 1: Ingestion
    print("─" * 40)
    print("STEP 1: INGESTION")
    print("─" * 40)
    signals = run_ingestion(run_date)

    if not signals:
        print("\n[Pipeline] No signals extracted. Pipeline complete (no brief generated).")
        return

    # Step 2: Analysis
    print("\n" + "─" * 40)
    print("STEP 2: ANALYSIS")
    print("─" * 40)
    analysis = run_analysis(signals, run_date)

    findings = analysis.get("findings", [])
    if not findings:
        print("\n[Pipeline] No findings produced. Pipeline complete (no brief generated).")
        return

    # Step 3: Brief Generation
    print("\n" + "─" * 40)
    print("STEP 3: BRIEF GENERATION")
    print("─" * 40)
    brief = run_brief(analysis, run_date)

    print(f"\n{'='*60}")
    print(f"  Pipeline complete. {len(signals)} signals → {len(findings)} findings → Brief")
    print(f"  Finished: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

    return brief


def run_thesis_pipeline(days_back: int = 7):
    """Execute the thesis synthesis pipeline."""
    print(f"\n{'='*60}")
    print(f"  CHARLIE — Thesis Synthesis")
    print(f"  {date.today().strftime('%A, %B %d, %Y')}")
    print(f"{'='*60}\n")

    proposal = run_thesis(days_back)

    if proposal:
        print(f"\n{'='*60}")
        print(f"  Thesis proposal generated. Awaiting review.")
        print(f"{'='*60}\n")
    else:
        print(f"\n{'='*60}")
        print(f"  No thesis proposal generated.")
        print(f"{'='*60}\n")

    return proposal


def main():
    parser = argparse.ArgumentParser(description="Charlie Orchestrator")
    parser.add_argument("--full", action="store_true", help="Run daily pipeline + thesis synthesis")
    parser.add_argument("--thesis", action="store_true", help="Run thesis synthesis only")
    parser.add_argument("--thesis-days", type=int, default=7, help="Days of signals for thesis (default: 7)")
    parser.add_argument("--date", type=str, default=None, help="Override run date (YYYY-MM-DD)")
    parser.add_argument("--test", action="store_true", help="Dry run with verbose output")

    args = parser.parse_args()

    # Parse date override
    run_date = None
    if args.date:
        run_date = date.fromisoformat(args.date)

    if args.test:
        print("[Test mode] Configuration:")
        print(f"  API Key: {'set' if config.api_key else 'NOT SET'}")
        print(f"  Daily model: {config.model_daily}")
        print(f"  Deep model: {config.model_deep}")
        print(f"  Data dir: {config.data_dir}")
        print(f"  Context dir: {config.context_dir}")
        return

    if args.thesis:
        run_thesis_pipeline(args.thesis_days)
    elif args.full:
        run_daily_pipeline(run_date)
        run_thesis_pipeline(args.thesis_days)
    else:
        run_daily_pipeline(run_date)


if __name__ == "__main__":
    main()
