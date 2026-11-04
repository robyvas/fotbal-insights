"""Serves the feed and the proof behind each card. Read-only.

Run with: .venv/bin/uvicorn insights.api:app --port 8765

Everything shown as a number outside the card text (big stat, comparison bars, proof table)
comes from the verified numbers and the raw tables, never from the model.
"""
import json
from functools import lru_cache
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .config import DB_PATH, ROOT, WRITTEN_FEED_PATH
from .generators import _n
from .verify import check_group

INDEX = Path(ROOT / "web" / "index.html")

app = FastAPI(title="Football Insights", docs_url="/api/docs", openapi_url="/api/openapi.json")

GROUP_LABELS = {
    "home_away": ["Acasă", "În deplasare"],
    "super_sub": ["Ca rezervă", "Ca titular"],
    "with_without": ["Cu el titular", "Fără el titular"],
}


@lru_cache
def connection():
    return duckdb.connect(str(DB_PATH), read_only=True)


@lru_cache
def feed() -> dict:
    if not WRITTEN_FEED_PATH.exists():
        raise RuntimeError("data/feed.json is missing: run python -m insights.write_feed")
    return json.loads(WRITTEN_FEED_PATH.read_text(encoding="utf-8"))


def _comma(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _bars(first_label, first, second_label, second) -> list[dict]:
    return [{"label": first_label, "value": first, "display": _pct(first), "scale": 1},
            {"label": second_label, "value": second, "display": _pct(second), "scale": 1}]


def stat_and_bars(card: dict) -> tuple[dict, list[dict]]:
    """The big number and the comparison, built only from the verified numbers."""
    kind, n = card["kind"], card["numbers"]
    if kind == "opponent_hot":
        return ({"value": f"{n['k']} din {n['n']}", "label": "meciuri cu gol"},
                _bars("Cu acest adversar", n["rate"], "În restul meciurilor", n["baseline"]))
    if kind == "opponent_cold":
        return ({"value": f"0 din {n['n']}", "label": "meciuri cu gol"},
                _bars("Cu acest adversar", 0, "În restul meciurilor", n["baseline"]))
    if kind == "home_away":
        return ({"value": f"{n['kh']} / {n['ka']}", "label": "meciuri cu gol, acasă / în deplasare"},
                _bars("Acasă", n["rate_home"], "În deplasare", n["rate_away"]))
    if kind == "scoring_streak":
        return ({"value": str(n["length"]), "label": f"apariții la rând cu gol, {_n(n['goals'], 'goluri', 'gol')}"}, [])
    if kind == "super_sub":
        scale = max(n["per90_sub"], n["per90_start"])
        return ({"value": str(n["goals_sub"]), "label": "goluri de pe bancă"}, [
            {"label": "Goluri la 90 de minute, ca rezervă", "value": n["per90_sub"], "display": _comma(n["per90_sub"], 2), "scale": scale},
            {"label": "Goluri la 90 de minute, ca titular", "value": n["per90_start"], "display": _comma(n["per90_start"], 2), "scale": scale},
        ])
    if kind == "recent_form":
        scale = max(n["goals"], n["expected"])
        return ({"value": str(n["goals"]), "label": "goluri în ultimele 10 apariții"}, [
            {"label": "Goluri marcate", "value": n["goals"], "display": str(n["goals"]), "scale": scale},
            {"label": "La ritmul de dinainte", "value": n["expected"], "display": f"cam {_comma(n['expected'], 1)}", "scale": scale},
        ])
    if kind == "team_head_to_head":
        return ({"value": f"{n['k']} din {n['n']}", "label": "victorii"},
                _bars("Cu acest adversar", n["rate"], "Cu restul echipelor", n["baseline"]))
    if kind == "with_without":
        return ({"value": f"{n['k_with']} din {n['n_with']}", "label": "victorii cu el titular"},
                _bars("Cu el titular", n["rate_with"], "Fără el titular", n["rate_without"]))
    raise ValueError(f"unknown kind {kind}")


def public_card(card_id: int, card: dict) -> dict:
    stat, bars = stat_and_bars(card)
    return {
        "id": card_id, "title": card["title"], "text": card["text"], "tier": card["tier"], "kind": card["kind"],
        "written_by": card["written_by"], "stat": stat, "bars": bars,
    }


def _player_rows(con, group) -> list[dict]:
    rows = con.execute("""
        SELECT g.date,
               CASE WHEN a.player_club_id = g.home_club_id THEN g.away_club_name ELSE g.home_club_name END,
               a.player_club_id = g.home_club_id, g.home_club_goals, g.away_club_goals, a.goals, a.minutes_played
        FROM raw_appearances a JOIN raw_games g USING (game_id)
        WHERE a.player_id = ? AND list_contains(?, a.game_id) ORDER BY g.date DESC
    """, [group["player_id"], group["game_ids"]]).fetchall()
    return [{"date": str(r[0]), "opponent": r[1], "home": r[2], "score": f"{r[3]}–{r[4]}", "goals": r[5], "minutes": r[6]}
            for r in rows]


def _club_rows(con, group) -> list[dict]:
    rows = con.execute("""
        SELECT date, CASE WHEN home_club_id = ? THEN away_club_name ELSE home_club_name END,
               home_club_id = ?, home_club_goals, away_club_goals,
               CASE WHEN home_club_id = ? THEN home_club_goals > away_club_goals ELSE away_club_goals > home_club_goals END
        FROM raw_games WHERE list_contains(?, game_id) ORDER BY date DESC
    """, [group["club_id"], group["club_id"], group["club_id"], group["game_ids"]]).fetchall()
    return [{"date": str(r[0]), "opponent": r[1], "home": r[2], "score": f"{r[3]}–{r[4]}", "won": r[5]} for r in rows]


@app.get("/api/feed")
def get_feed() -> dict:
    data = feed()
    return {
        "data_as_of": data["data_as_of"], "model": data["model"],
        "cards": [public_card(i, card) for i, card in enumerate(data["cards"])],
    }


@app.get("/api/cards/{card_id}/evidence")
def get_evidence(card_id: int) -> dict:
    cards = feed()["cards"]
    if not 0 <= card_id < len(cards):
        raise HTTPException(status_code=404, detail="card not found")
    card = cards[card_id]
    con = connection().cursor()
    labels = GROUP_LABELS.get(card["kind"], ["Meciurile din spatele cifrelor"])
    groups = []
    for label, group in zip(labels, card["evidence"]):
        error = check_group(con, group)  # recounted on every request, from the raw tables
        rows = _club_rows(con, group) if group["metric"] == "won" else _player_rows(con, group)
        groups.append({"label": label, "metric": group["metric"], "k": group["k"], "n": group["n"],
                       "recount_ok": error is None, "recount_error": error, "rows": rows})
    return {"verified_fact": card["verified_fact"], "groups": groups}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(INDEX)
