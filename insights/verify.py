"""Recount every number an insight claims, straight from the raw tables.

Deliberately uses only raw_* tables and none of the generator logic, so a bug in a
generator or in the derived tables shows up here as a failure.
"""


def check_group(con, group) -> str | None:
    """Return an error message if an evidence group does not reproduce, else None."""
    ids = group["game_ids"]
    if len(set(ids)) != len(ids):
        return "duplicate game ids"
    if len(ids) != group["n"]:
        return f"n={group['n']} but {len(ids)} game ids"
    metric = group["metric"]
    if metric in ("scored", "goals"):
        rows = con.execute(
            "SELECT goals FROM raw_appearances WHERE player_id = ? AND list_contains(?, game_id)",
            [group["player_id"], ids],
        ).fetchall()
        if len(rows) != len(ids):
            return f"{len(rows)} appearances found for {len(ids)} games"
        actual = sum(r[0] > 0 for r in rows) if metric == "scored" else sum(r[0] for r in rows)
    elif metric == "won":
        rows = con.execute(
            """SELECT CASE WHEN home_club_id = ? THEN home_club_goals > away_club_goals
                           WHEN away_club_id = ? THEN away_club_goals > home_club_goals END
               FROM raw_games WHERE list_contains(?, game_id)""",
            [group["club_id"], group["club_id"], ids],
        ).fetchall()
        if len(rows) != len(ids) or any(r[0] is None for r in rows):
            return "club did not play in all listed games"
        actual = sum(bool(r[0]) for r in rows)
    else:
        return f"unknown metric {metric}"
    if actual != group["k"]:
        return f"claimed {group['k']}, recounted {actual}"
    return None


def verify_insight(con, insight) -> list[str]:
    return [e for g in insight["evidence"] if (e := check_group(con, g))]
