import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Central configuration for Charlie."""

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in environment")

        # Models
        self.model_daily = os.getenv("MODEL_DAILY", "claude-sonnet-4-6")
        self.model_deep = os.getenv("MODEL_DEEP", "claude-opus-4-6")

        # Paths
        self.project_root = Path(__file__).parent.parent
        self.data_dir = self.project_root / os.getenv("DATA_DIR", "data")
        self.context_dir = self.project_root / "context"

        # Ensure data directories exist
        for subdir in ["signals", "briefs", "thesis", "thesis/history", "watchlists", "adversary", "logs",
                       "field", "field/artifacts", "field/originals", "field/extracted"]:
            (self.data_dir / subdir).mkdir(parents=True, exist_ok=True)

        # Scheduling
        self.brief_hour = int(os.getenv("BRIEF_HOUR", "6"))
        self.brief_timezone = os.getenv("BRIEF_TIMEZONE", "America/Los_Angeles")

    @property
    def signals_dir(self):
        return self.data_dir / "signals"

    @property
    def briefs_dir(self):
        return self.data_dir / "briefs"

    @property
    def thesis_dir(self):
        return self.data_dir / "thesis"

    @property
    def watchlists_dir(self):
        return self.data_dir / "watchlists"

    @property
    def field_dir(self):
        return self.data_dir / "field"


config = Config()
