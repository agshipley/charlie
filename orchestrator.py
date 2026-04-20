"""
Charlie Orchestrator — coordinates agent execution on scheduled cadences.

This is the main entry point. When run, it determines which agents need to
execute based on the current schedule and runs them in sequence.

Daily pipeline: Ingestion → Analysis → Brief
Weekly pipeline: Thesis Synthesis (produces proposal for review)

Usage:
    python orchestrator.py                         # Run the daily pipeline
    python orchestrator.py --full                  # Run daily + thesis synthesis
    python orchestrator.py --thesis                # Run thesis synthesis only
    python orchestrator.py --test                  # Dry run with verbose output

Field Phase 2 manual-trigger paths (write to disk, no dry-run):
    python orchestrator.py --thesis --with-field   # Thesis with Field Work wiring
    python orchestrator.py --brief --with-field    # Re-run today's brief with Field Work
    python orchestrator.py --adversary --with-field # Re-run adversary with Field Work
"""

import argparse
from datetime import date, datetime

from core.config import config
from core.logging import configure_logging, get_logger
from core.render import render_brief, render_thesis_proposal
from agents.ingestion import run_ingestion
from agents.analysis import run_analysis
from agents.brief import run_brief
from agents.adversary import run_adversary
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

    # Step 3.5: Adversarial Review
    print("\n" + "─" * 40)
    print("STEP 3.5: ADVERSARIAL REVIEW")
    print("─" * 40)
    adversary = run_adversary(brief, run_date)

    # Step 4: Render readable output
    print("\n" + "─" * 40)
    print("STEP 4: RENDER")
    print("─" * 40)
    md_path = render_brief(brief, signals=signals, findings=analysis, run_date=run_date, adversary=adversary)
    print(f"[Pipeline] Readable brief: {md_path}")

    null_finding = adversary.get("null_finding", True) if adversary else True
    adversary_note = "no findings" if null_finding else "findings present (shadow mode)"
    print(f"\n{'='*60}")
    print(f"  Pipeline complete. {len(signals)} signals → {len(findings)} findings → Brief")
    print(f"  Adversary: {adversary_note}")
    print(f"  Readable output: {md_path}")
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
        md_path = render_thesis_proposal(proposal)
        print(f"\n{'='*60}")
        print(f"  Thesis proposal generated. Awaiting review.")
        print(f"  Readable output: {md_path}")
        print(f"{'='*60}\n")
    else:
        print(f"\n{'='*60}")
        print(f"  No thesis proposal generated.")
        print(f"{'='*60}\n")

    return proposal


def _confirm(prompt: str) -> bool:
    """Ask for y/N confirmation. Returns True only on explicit 'y'."""
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer == "y"


def run_thesis_with_field(days_back: int = 7):
    """Run thesis synthesis with Field Work wiring. Overwrites today's proposal."""
    today = date.today()
    print(f"\n{'='*60}")
    print(f"  CHARLIE — Thesis Synthesis (with Field Work)")
    print(f"  {today.strftime('%A, %B %d, %Y')}")
    print(f"{'='*60}\n")
    if not _confirm("This will overwrite today's thesis proposal. Proceed?"):
        print("Aborted.")
        return
    proposal = run_thesis(days_back)
    if proposal:
        md_path = render_thesis_proposal(proposal)
        print(f"\n[Pipeline] Thesis proposal saved. Readable output: {md_path}")
    return proposal


def run_brief_with_field(run_date: date | None = None):
    """Re-run today's brief generator with Field Work wiring against saved signals."""
    from agents.analysis import run_analysis
    from core.state import StateManager
    run_date = run_date or date.today()
    print(f"\n{'='*60}")
    print(f"  CHARLIE — Brief Generation (with Field Work)")
    print(f"  {run_date.strftime('%A, %B %d, %Y')}")
    print(f"{'='*60}\n")
    if not _confirm(f"This will overwrite today's brief ({run_date.isoformat()}). Proceed?"):
        print("Aborted.")
        return
    state = StateManager()
    signals = state.load_signals(run_date)
    if not signals:
        print(f"[Pipeline] No signals found for {run_date.isoformat()}. Cannot re-run brief.")
        return
    print(f"[Pipeline] Loaded {len(signals)} signals for {run_date.isoformat()}")
    analysis = run_analysis(signals, run_date)
    findings = analysis.get("findings", [])
    if not findings:
        print("[Pipeline] No findings produced. Cannot generate brief.")
        return
    brief = run_brief(analysis, run_date)
    adversary = run_adversary(brief, run_date)
    md_path = render_brief(brief, signals=signals, findings=analysis, run_date=run_date, adversary=adversary)
    print(f"\n[Pipeline] Brief saved. Readable output: {md_path}")
    return brief


def run_adversary_with_field(run_date: date | None = None):
    """Re-run adversary against today's brief with Field Work wiring."""
    from core.state import StateManager
    run_date = run_date or date.today()
    print(f"\n{'='*60}")
    print(f"  CHARLIE — Adversary Review (with Field Work)")
    print(f"  {run_date.strftime('%A, %B %d, %Y')}")
    print(f"{'='*60}\n")
    if not _confirm(f"This will overwrite today's adversary output ({run_date.isoformat()}). Proceed?"):
        print("Aborted.")
        return
    state = StateManager()
    brief = state.load_brief(run_date)
    if not brief:
        print(f"[Pipeline] No brief found for {run_date.isoformat()}. Run --brief first.")
        return
    adversary = run_adversary(brief, run_date)
    print(f"\n[Pipeline] Adversary output saved for {run_date.isoformat()}.")
    return adversary


def main():
    configure_logging()
    log = get_logger(__name__)
    log.info("orchestrator_started")

    parser = argparse.ArgumentParser(description="Charlie Orchestrator")
    parser.add_argument("--full", action="store_true", help="Run daily pipeline + thesis synthesis")
    parser.add_argument("--thesis", action="store_true", help="Run thesis synthesis only")
    parser.add_argument("--brief", action="store_true", help="Re-run today's brief against saved signals")
    parser.add_argument("--adversary", action="store_true", help="Re-run adversary against today's saved brief")
    parser.add_argument("--with-field", action="store_true", help="Enable Field Work wiring (Phase 2)")
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

    # ── Field Phase 2 manual-trigger paths ───────────────────────────────
    if args.with_field:
        if args.thesis:
            run_thesis_with_field(args.thesis_days)
        elif args.brief:
            run_brief_with_field(run_date)
        elif args.adversary:
            run_adversary_with_field(run_date)
        else:
            print("--with-field requires --thesis, --brief, or --adversary")
        return

    # ── Standard paths ────────────────────────────────────────────────────
    if args.thesis:
        run_thesis_pipeline(args.thesis_days)
    elif args.adversary:
        run_date = run_date or date.today()
        from core.state import StateManager
        brief = StateManager().load_brief(run_date)
        if brief:
            run_adversary(brief, run_date)
        else:
            print(f"No brief found for {run_date.isoformat()}")
    elif args.full:
        run_daily_pipeline(run_date)
        run_thesis_pipeline(args.thesis_days)
    else:
        run_daily_pipeline(run_date)


if __name__ == "__main__":
    main()