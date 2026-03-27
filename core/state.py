import json
from datetime import datetime, date
from pathlib import Path
from .config import config


class StateManager:
    """
    Manages persistent state for Charlie using JSON files.

    This is intentionally simple — JSON files on disk. For a personal tool
    this is perfectly adequate and avoids database overhead. State is organized
    as:
        data/signals/          — daily signal extractions, one file per run
        data/briefs/           — generated briefs, one file per day
        data/thesis/current.json   — the current thesis document
        data/thesis/history/   — timestamped thesis versions
        data/watchlists/       — entity and pattern watchlists
    """

    def __init__(self):
        self.data_dir = config.data_dir

    # ── Signals ──────────────────────────────────────────────────────────

    def save_signals(self, signals: list[dict], run_date: date | None = None):
        """Save extracted signals from an ingestion run."""
        run_date = run_date or date.today()
        path = config.signals_dir / f"{run_date.isoformat()}.json"
        self._write(path, {
            "date": run_date.isoformat(),
            "extracted_at": datetime.now().isoformat(),
            "signals": signals,
        })
        return path

    def load_signals(self, run_date: date) -> list[dict]:
        """Load signals for a specific date."""
        path = config.signals_dir / f"{run_date.isoformat()}.json"
        data = self._read(path)
        return data.get("signals", []) if data else []

    def load_recent_signals(self, days: int = 7) -> list[dict]:
        """Load signals from the last N days."""
        all_signals = []
        today = date.today()
        for i in range(days):
            d = date.fromordinal(today.toordinal() - i)
            signals = self.load_signals(d)
            for s in signals:
                s["_source_date"] = d.isoformat()
            all_signals.extend(signals)
        return all_signals

    # ── Briefs ───────────────────────────────────────────────────────────

    def save_brief(self, brief: dict, run_date: date | None = None):
        """Save a generated brief."""
        run_date = run_date or date.today()
        path = config.briefs_dir / f"{run_date.isoformat()}.json"
        self._write(path, {
            "date": run_date.isoformat(),
            "generated_at": datetime.now().isoformat(),
            "brief": brief,
        })
        return path

    def load_brief(self, run_date: date) -> dict | None:
        """Load a brief for a specific date."""
        path = config.briefs_dir / f"{run_date.isoformat()}.json"
        data = self._read(path)
        return data.get("brief") if data else None

    # ── Thesis ───────────────────────────────────────────────────────────

    def load_thesis(self) -> dict | None:
        """Load the current thesis document."""
        path = config.thesis_dir / "current.json"
        return self._read(path)

    def save_thesis(self, thesis: dict):
        """Save the current thesis, archiving the previous version."""
        current_path = config.thesis_dir / "current.json"

        # Archive existing version if present
        existing = self._read(current_path)
        if existing:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            history_path = config.thesis_dir / "history" / f"{timestamp}.json"
            self._write(history_path, existing)

        thesis["updated_at"] = datetime.now().isoformat()
        self._write(current_path, thesis)
        return current_path

    def save_thesis_proposal(self, proposal: dict):
        """Save a proposed thesis update for Andrew to review."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.thesis_dir / f"proposal_{timestamp}.json"
        proposal["proposed_at"] = datetime.now().isoformat()
        proposal["status"] = "pending_review"
        self._write(path, proposal)
        return path

    # ── Watchlists ───────────────────────────────────────────────────────

    def load_watchlist(self, name: str = "default") -> dict:
        """Load a watchlist by name."""
        path = config.watchlists_dir / f"{name}.json"
        return self._read(path) or {"companies": [], "people": [], "patterns": []}

    def save_watchlist(self, watchlist: dict, name: str = "default"):
        """Save a watchlist."""
        path = config.watchlists_dir / f"{name}.json"
        watchlist["updated_at"] = datetime.now().isoformat()
        self._write(path, watchlist)
        return path

    # ── Context (Liz) ────────────────────────────────────────────────────

    def load_context(self) -> dict:
        """Load all of Liz's persistent context files."""
        context = {}
        for name in ["profile", "slate", "watching"]:
            path = config.context_dir / f"{name}.json"
            data = self._read(path)
            if data:
                context[name] = data
        return context

    # ── Utilities ────────────────────────────────────────────────────────

    def _read(self, path: Path) -> dict | None:
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
        return None

    def _write(self, path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
