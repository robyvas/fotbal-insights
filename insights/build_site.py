"""Export the feed and the proof behind each card to site/feed.json.

The data is frozen, so the page needs no server. Every number is recounted from the raw
tables here, and the build stops if any recount fails.

Everything shown as a number outside the card text (big stat, comparison bars, proof table)
comes from the verified numbers and the raw tables, never from the model.

Usage: python -m insights.build_site
"""
import json

import duckdb

from .config import DB_PATH, ROOT, WRITTEN_FEED_PATH
from .generators import _n
from .verify import check_group

SITE_FEED_PATH = ROOT / "site" / "feed.json"

GROUP_LABELS = {
    "home_away": ["At home", "Away"],
    "super_sub": ["As a substitute", "As a starter"],
    "with_without": ["With the player starting", "Without the player starting"],
}


def _fixed(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _bars(first_label, first, second_label, second) -> list[dict]:
    return [{"label": first_label, "value": first, "display": _pct(first), "scale": 1},
            {"label": second_label, "value": second, "display": _pct(second), "scale": 1}]


def stat_and_bars(card: dict) -> tuple[dict, list[dict]]:
    """The big number and the comparison, built only from the verified numbers."""
    kind, n = card["kind"], card["numbers"]
    if kind == "opponent_hot":
        return ({"value": f"{n['k']} of {n['n']}", "label": "games with a goal"},
                _bars("Against this opponent", n["rate"], "In the other games", n["baseline"]))
    if kind == "opponent_cold":
        return ({"value": f"0 of {n['n']}", "label": "games with a goal"},
                _bars("Against this opponent", 0, "In the other games", n["baseline"]))
    if kind == "home_away":
        return ({"value": f"{n['kh']} / {n['ka']}", "label": "games with a goal, home / away"},
                _bars("At home", n["rate_home"], "Away", n["rate_away"]))
    if kind == "scoring_streak":
        return ({"value": str(n["length"]), "label": f"straight appearances with a goal, {_n(n['goals'], 'goals', 'goal')} in total"}, [])
    if kind == "super_sub":
        scale = max(n["per90_sub"], n["per90_start"])
        return ({"value": str(n["goals_sub"]), "label": "goals off the bench"}, [
            {"label": "Goals per 90 minutes, as a substitute", "value": n["per90_sub"], "display": _fixed(n["per90_sub"], 2), "scale": scale},
            {"label": "Goals per 90 minutes, as a starter", "value": n["per90_start"], "display": _fixed(n["per90_start"], 2), "scale": scale},
        ])
    if kind == "recent_form":
        scale = max(n["goals"], n["expected"])
        return ({"value": str(n["goals"]), "label": "goals in the last 10 appearances"}, [
            {"label": "Goals scored", "value": n["goals"], "display": str(n["goals"]), "scale": scale},
            {"label": "At the earlier rate", "value": n["expected"], "display": f"about {_fixed(n['expected'], 1)}", "scale": scale},
        ])
    if kind == "team_head_to_head":
        return ({"value": f"{n['k']} of {n['n']}", "label": "wins"},
                _bars("Against this opponent", n["rate"], "Against other clubs", n["baseline"]))
    if kind == "with_without":
        return ({"value": f"{n['k_with']} of {n['n_with']}", "label": "wins with the player starting"},
                _bars("With the player starting", n["rate_with"], "Without the player starting", n["rate_without"]))
    raise ValueError(f"unknown kind {kind}")


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


def proof_for(con, card: dict) -> dict:
    """The matches behind a card. Raises if a claimed number does not recount."""
    labels = GROUP_LABELS.get(card["kind"], ["The games behind the numbers"])
    groups = []
    for label, group in zip(labels, card["evidence"]):
        if error := check_group(con, group):
            raise ValueError(f"{card['verified_fact']}: {error}")
        rows = _club_rows(con, group) if group["metric"] == "won" else _player_rows(con, group)
        groups.append({"label": label, "metric": group["metric"], "k": group["k"], "n": group["n"], "rows": rows})
    return {"verified_fact": card["verified_fact"], "groups": groups}


def public_card(con, card: dict) -> dict:
    stat, bars = stat_and_bars(card)
    return {
        "title": card["title"], "text": card["text"], "tier": card["tier"], "kind": card["kind"],
        "written_by": card["written_by"], "stat": stat, "bars": bars, "proof": proof_for(con, card),
    }


def build() -> dict:
    data = json.loads(WRITTEN_FEED_PATH.read_text(encoding="utf-8"))
    con = duckdb.connect(str(DB_PATH), read_only=True)
    site = {"data_as_of": data["data_as_of"], "model": data["model"],
            "cards": [public_card(con, card) for card in data["cards"]]}
    con.close()
    return site


def main() -> None:
    site = build()
    SITE_FEED_PATH.write_text(json.dumps(site, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(site['cards'])} cards recounted, {SITE_FEED_PATH.stat().st_size // 1024} KB written to {SITE_FEED_PATH}")


if __name__ == "__main__":
    main()
