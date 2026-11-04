"""Paths and tunable thresholds. Everything that changes what counts as an insight lives here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "football.duckdb"
FEED_PATH = ROOT / "data" / "insights.json"

BASE_URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"
TABLES = ["appearances", "games", "players", "clubs", "competitions", "game_lineups", "game_events"]

# A league is used for player insights only if this share of its club-game
# records passes the completeness check in build_db.py.
MIN_LEAGUE_TRUST = 0.90

# False discovery rate applied inside each generator, over every combination tested.
# Of the patterns kept, about this share may still be luck. The numbers themselves are
# always exact: verify.py recounts them from the raw tables.
FDR = 0.10

# Scoring in this many consecutive league appearances is a record-tier streak.
RECORD_STREAK_MIN = 10

TOP5 = {"GB1", "ES1", "IT1", "L1", "FR1"}

# Weights for the final feed score. Surprise = how unlikely, relevance = how much people care.
SURPRISE_WEIGHT = 0.6
RELEVANCE_WEIGHT = 0.4
SURPRISE_CAP = 10.0  # -log10(adjusted p) at which surprise reaches 1.0
TEAM_RELEVANCE = {"top5": 0.7, "RO1": 0.8, "other": 0.45}

# Model-written feed
LLM_MODEL = "gemini-3.1-flash-lite"  # cheapest text model this key can use, Nov 2026
LLM_CACHE_DIR = ROOT / "data" / "llm_cache"
WRITTEN_FEED_PATH = ROOT / "data" / "feed.json"
MAX_REWRITES = 2
