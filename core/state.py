import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from .config import config
from .logging import get_logger

_log = get_logger(__name__)


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
        _log.debug("state_write_attempt", method="save_signals", path=str(path), count=len(signals))
        try:
            self._write(path, {
                "date": run_date.isoformat(),
                "extracted_at": datetime.now().isoformat(),
                "signals": signals,
            })
            _log.info("state_write_success", method="save_signals", path=str(path), count=len(signals))
        except Exception as exc:
            _log.error("state_write_failed", method="save_signals", path=str(path), exc_info=True)
            raise
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
        _log.debug("state_write_attempt", method="save_brief", path=str(path))
        try:
            self._write(path, {
                "date": run_date.isoformat(),
                "generated_at": datetime.now().isoformat(),
                "brief": brief,
            })
            _log.info("state_write_success", method="save_brief", path=str(path))
        except Exception as exc:
            _log.error("state_write_failed", method="save_brief", path=str(path), exc_info=True)
            raise
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
        _log.debug("state_write_attempt", method="save_thesis", path=str(current_path))
        try:
            # Archive existing version if present
            existing = self._read(current_path)
            if existing:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                history_path = config.thesis_dir / "history" / f"{timestamp}.json"
                self._write(history_path, existing)

            thesis["updated_at"] = datetime.now().isoformat()
            self._write(current_path, thesis)
            _log.info("state_write_success", method="save_thesis", path=str(current_path))
        except Exception as exc:
            _log.error("state_write_failed", method="save_thesis", path=str(current_path), exc_info=True)
            raise
        return current_path

    def save_thesis_proposal(self, proposal: dict) -> Path:
        """Save a thesis proposal for review."""
        proposals_dir = config.thesis_dir / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)

        proposal.setdefault("iteration", 0)
        proposal.setdefault("max_iterations", 5)
        proposal.setdefault("status", "pending")
        proposal.setdefault("history", [
            {"iteration": 0, "type": "synthesis", "timestamp": datetime.now().isoformat()}
        ])
        for key in ("extensions", "revisions", "new_patterns"):
            for item in proposal.get(key, []):
                item.setdefault("flag", None)
                item.setdefault("annotation", None)

        path = proposals_dir / f"{date.today().isoformat()}.json"
        _log.debug("state_write_attempt", method="save_thesis_proposal", path=str(path))
        try:
            with open(path, "w") as f:
                json.dump(proposal, f, indent=2, default=str)
            _log.info("state_write_success", method="save_thesis_proposal", path=str(path))
        except Exception as exc:
            _log.error("state_write_failed", method="save_thesis_proposal", path=str(path), exc_info=True)
            raise
        return path

    def load_latest_proposal(self) -> tuple:
        """Load the most recent thesis proposal. Returns (proposal, path) or (None, None)."""
        proposals_dir = config.thesis_dir / "proposals"
        if not proposals_dir.exists():
            return None, None
        files = sorted(proposals_dir.glob("*.json"), reverse=True)
        if not files:
            return None, None
        with open(files[0]) as f:
            return json.load(f), files[0]

    def save_proposal_update(self, proposal: dict, path: Path):
        """Overwrite an existing proposal file (after annotation or refinement)."""
        _log.debug("state_write_attempt", method="save_proposal_update", path=str(path))
        try:
            with open(path, "w") as f:
                json.dump(proposal, f, indent=2, default=str)
            _log.info("state_write_success", method="save_proposal_update", path=str(path))
        except Exception as exc:
            _log.error("state_write_failed", method="save_proposal_update", path=str(path), exc_info=True)
            raise

    # ── Watchlists ───────────────────────────────────────────────────────

    def load_watchlist(self, name: str = "default") -> dict:
        """Load a watchlist by name."""
        path = config.watchlists_dir / f"{name}.json"
        return self._read(path) or {"companies": [], "people": [], "patterns": []}

    def save_watchlist(self, watchlist: dict, name: str = "default"):
        """Save a watchlist."""
        path = config.watchlists_dir / f"{name}.json"
        _log.debug("state_write_attempt", method="save_watchlist", path=str(path), name=name)
        try:
            watchlist["updated_at"] = datetime.now().isoformat()
            self._write(path, watchlist)
            _log.info("state_write_success", method="save_watchlist", path=str(path), name=name)
        except Exception as exc:
            _log.error("state_write_failed", method="save_watchlist", path=str(path), exc_info=True)
            raise
        return path

    # ── Sessions ─────────────────────────────────────────────────────────

    def load_sessions(self, days_back: int = 14) -> list[dict]:
        """Load recent session entries from data/sessions.json."""
        path = config.data_dir / "sessions.json"
        if not path.exists():
            return []
        with open(path) as f:
            data = json.load(f)
        cutoff = (date.today() - timedelta(days=days_back)).isoformat()
        return [s for s in data.get("sessions", []) if s["brief_date"] >= cutoff]

    def append_session(self, entry: dict):
        """Append a session entry to data/sessions.json."""
        path = config.data_dir / "sessions.json"
        _log.debug("state_write_attempt", method="append_session", id=entry.get("id"))
        try:
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
            else:
                data = {"sessions": []}
            data["sessions"].append(entry)
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            _log.info("state_write_success", method="append_session", id=entry.get("id"))
        except Exception as exc:
            _log.error("state_write_failed", method="append_session", id=entry.get("id"), exc_info=True)
            raise

    # ── Adversary ────────────────────────────────────────────────────────

    def save_adversary(self, adversary: dict, run_date: date | None = None) -> Path:
        """Save adversary critique output for a run date."""
        run_date = run_date or date.today()
        adversary_dir = self.data_dir / "adversary"
        adversary_dir.mkdir(parents=True, exist_ok=True)
        path = adversary_dir / f"{run_date.isoformat()}.json"
        _log.debug("state_write_attempt", method="save_adversary", path=str(path))
        try:
            self._write(path, adversary)
            _log.info("state_write_success", method="save_adversary", path=str(path))
        except Exception as exc:
            _log.error("state_write_failed", method="save_adversary", path=str(path), exc_info=True)
            raise
        return path

    def load_adversary(self, run_date: date) -> dict | None:
        """Load adversary output for a specific date."""
        path = self.data_dir / "adversary" / f"{run_date.isoformat()}.json"
        return self._read(path)

    def save_adversary_feedback(self, entry: dict) -> None:
        """Append a single feedback entry to data/adversary/feedback.json."""
        path = self.data_dir / "adversary" / "feedback.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        _log.debug("state_write_attempt", method="save_adversary_feedback", id=entry.get("id"))
        try:
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
            else:
                data = {"feedback": []}
            data["feedback"].append(entry)
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            _log.info("state_write_success", method="save_adversary_feedback", id=entry.get("id"))
        except Exception as exc:
            _log.error("state_write_failed", method="save_adversary_feedback", id=entry.get("id"), exc_info=True)
            raise

    def load_adversary_feedback(self, days_back: int = 30) -> list:
        """Load feedback entries within the window, sorted newest first."""
        path = self.data_dir / "adversary" / "feedback.json"
        if not path.exists():
            return []
        with open(path) as f:
            data = json.load(f)
        cutoff = (date.today() - timedelta(days=days_back)).isoformat()
        entries = [e for e in data.get("feedback", []) if e.get("adversary_date", "") >= cutoff]
        return sorted(entries, key=lambda e: e.get("submitted_at", ""), reverse=True)

    def load_recent_briefs(self, days: int = 14) -> list[dict]:
        """Load briefs from the last N days (excluding today), returning the brief sub-dict for each."""
        results = []
        today = date.today()
        for i in range(1, days + 1):  # start at 1 to exclude today (passed explicitly to adversary)
            d = date.fromordinal(today.toordinal() - i)
            brief = self.load_brief(d)
            if brief:
                brief["date"] = d.isoformat()
                results.append(brief)
        return results

    # ── Context (Liz) ────────────────────────────────────────────────────

    def load_context(self) -> dict:
        """Load all of Liz's persistent context files."""
        context = {}
        for name in ["profile", "slate", "watching", "sessions"]:
            path = config.context_dir / f"{name}.json"
            data = self._read(path)
            if data:
                context[name] = data
        return context

    # ── Field Work ───────────────────────────────────────────────────────

    def save_field_artifact(self, artifact: dict) -> Path:
        """Save a field artifact metadata record."""
        path = config.field_dir / "artifacts" / f"{artifact['id']}.json"
        _log.debug("state_write_attempt", method="save_field_artifact", path=str(path))
        try:
            self._atomic_write_json(path, artifact)
        except Exception:
            _log.error("state_write_failed", method="save_field_artifact", path=str(path), exc_info=True)
            raise
        return path

    def load_field_artifact(self, artifact_id: str) -> dict | None:
        """Load a single field artifact by ID."""
        path = config.field_dir / "artifacts" / f"{artifact_id}.json"
        return self._read(path)

    def list_field_artifacts(self) -> list[dict]:
        """Return all field artifacts sorted newest first."""
        artifacts_dir = config.field_dir / "artifacts"
        if not artifacts_dir.exists():
            return []
        artifacts = []
        for p in artifacts_dir.glob("*.json"):
            data = self._read(p)
            if data:
                artifacts.append(data)
        artifacts.sort(key=lambda a: a.get("uploaded_at", ""), reverse=True)
        return artifacts

    def save_field_extracted(self, artifact_id: str, extracted: dict) -> Path:
        """Save extracted content for a field artifact."""
        path = config.field_dir / "extracted" / f"{artifact_id}.json"
        _log.debug("state_write_attempt", method="save_field_extracted", path=str(path))
        try:
            self._atomic_write_json(path, extracted)
        except Exception:
            _log.error("state_write_failed", method="save_field_extracted", path=str(path), exc_info=True)
            raise
        return path

    def load_field_extracted(self, artifact_id: str) -> dict | None:
        """Load extracted content for a field artifact."""
        path = config.field_dir / "extracted" / f"{artifact_id}.json"
        return self._read(path)

    # ── Utilities ────────────────────────────────────────────────────────

    def _atomic_write_json(self, path: Path, data: dict) -> None:
        """Write JSON atomically: write to .tmp, fsync, then os.replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            _log.info("state_write_success", method="_atomic_write_json", path=str(path))
        except Exception:
            _log.error("state_write_failed", method="_atomic_write_json", path=str(path), exc_info=True)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def _read(self, path: Path) -> dict | None:
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
        return None

    def _write(self, path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)