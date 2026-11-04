"""Checks against the real database and against facts known independently of this data."""
import copy

import duckdb
import pytest

from insights.config import DB_PATH, FDR
from insights.generators import _n, scoring_streak
from insights.run import generate
from insights.verify import verify_insight


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("run `python -m insights.build_db` first")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def feed(con):
    return generate(con)


@pytest.mark.parametrize("name, length, goals", [
    ("Lionel Messi", 21, 33),       # La Liga record run, 2012/13
    ("Jamie Vardy", 11, 13),        # Premier League record run, 2015
    ("Fabio Quagliarella", 11, 14), # Serie A run, 2018/19
])
def test_finds_known_record_streaks(con, name, length, goals):
    streaks, _ = scoring_streak(con)
    match = [s for s in streaks if s["fact"].startswith(name)]
    assert match, f"{name} missing from streaks"
    assert match[0]["numbers"]["length"] == length
    assert match[0]["numbers"]["goals"] == goals


def test_messi_2012_13_league_season_matches_official_totals(con):
    apps, goals = con.execute(
        "SELECT count(*), sum(goals) FROM appearance WHERE player_id = 28003 "
        "AND competition_id = 'ES1' AND season = 2012"
    ).fetchone()
    assert (apps, goals) == (32, 46)


def test_leagues_without_player_data_are_excluded_from_player_insights(con):
    assert con.execute(
        "SELECT count(*) FROM appearance WHERE competition_id IN ('RO1', 'MLS1', 'BRA1')"
    ).fetchone()[0] == 0


def test_every_appearance_comes_from_a_reconciled_club_game(con):
    assert con.execute("""
        SELECT count(*) FROM appearance a JOIN club_game g USING (game_id, club_id) WHERE NOT g.trusted
    """).fetchone()[0] == 0


def test_all_generated_insights_pass_verification(feed):
    insights, failures = feed
    assert insights
    assert failures == []


def test_confirmed_tier_really_passed_the_correction_and_tiers_are_known(feed):
    insights, _ = feed
    assert {i["tier"] for i in insights} <= {"confirmed", "record", "notable"}
    assert all(i["adjusted_p"] < FDR for i in insights if i["tier"] == "confirmed")
    assert all(i["adjusted_p"] >= FDR for i in insights if i["tier"] == "notable")


def test_verifier_catches_a_tampered_count(con, feed):
    insights, _ = feed
    tampered = copy.deepcopy(insights[0])
    tampered["evidence"][0]["k"] += 1
    assert verify_insight(con, tampered)


def test_verifier_catches_a_game_the_player_did_not_play(con, feed):
    insights, _ = feed
    player_insight = next(i for i in insights if i["evidence"][0]["metric"] in ("scored", "goals"))
    tampered = copy.deepcopy(player_insight)
    tampered["evidence"][0]["game_ids"][0] = -1
    assert verify_insight(con, tampered)


def test_no_streak_spans_an_untrusted_game(con):
    streaks, _ = scoring_streak(con)
    for streak in streaks:
        numbers = streak["numbers"]
        ids = streak["evidence"][0]["game_ids"]
        club_id = con.execute(
            "SELECT player_club_id FROM raw_appearances WHERE game_id = ? AND player_id = ?",
            [ids[0], streak["subject_id"]],
        ).fetchone()[0]
        bad = con.execute(
            "SELECT count(*) FROM club_game WHERE club_id = ? AND competition_id = ? AND NOT trusted "
            "AND date BETWEEN ? AND ?",
            [club_id, numbers["competition"], numbers["from"], numbers["to"]],
        ).fetchone()[0]
        assert bad == 0, streak["fact"]


def test_without_games_never_fall_outside_the_players_starting_period(con, feed):
    insights, _ = feed
    for insight in (i for i in insights if i["kind"] == "with_without"):
        started, without = insight["evidence"]
        outside = con.execute("""
            WITH spans AS (
                SELECT season, min(date) d1, max(date) d2 FROM raw_games
                WHERE list_contains(?, game_id) GROUP BY 1
            )
            SELECT count(*) FROM raw_games g LEFT JOIN spans s USING (season)
            WHERE list_contains(?, g.game_id) AND (s.season IS NULL OR g.date NOT BETWEEN s.d1 AND s.d2)
        """, [started["game_ids"], without["game_ids"]]).fetchone()[0]
        assert outside == 0, insight["fact"]


@pytest.mark.parametrize("count, expected", [(1, "1 goal"), (5, "5 goals"), (33, "33 goals")])
def test_number_agreement(count, expected):
    assert _n(count, "goals", "goal") == expected
