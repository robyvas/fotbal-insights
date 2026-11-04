"""Download the Transfermarkt CSVs and build data/football.duckdb.

The central table is `club_game`: one row per club per game, with a `trusted` flag.
A record is trusted only when it can be reconciled with the final score, because a
missing appearance would otherwise turn into a false claim ("scored in every game").
"""
import urllib.request

import duckdb

from .config import BASE_URL, DB_PATH, MIN_LEAGUE_TRUST, RAW_DIR, TABLES


def download() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        path = RAW_DIR / f"{table}.csv.gz"
        if not path.exists():
            print(f"downloading {table}")
            urllib.request.urlretrieve(f"{BASE_URL}/{table}.csv.gz", path)


SCHEMA = """
-- Lineups contain a few duplicates (same player listed twice in one game).
CREATE TABLE lineup AS
SELECT game_id, player_id, any_value(club_id) AS club_id,
       bool_or(type = 'starting_lineup') AS started
FROM raw_game_lineups GROUP BY 1, 2;

CREATE TABLE club_game AS
WITH apps AS (
    SELECT game_id, player_club_id AS club_id, sum(goals) AS player_goals, count(*) AS apps
    FROM raw_appearances GROUP BY 1, 2
), own_goals AS (
    -- Own goals are recorded under the club that benefited.
    SELECT game_id, club_id, count(*) AS own_goals FROM raw_game_events
    WHERE type = 'Goals' AND lower(description) LIKE '%own%' GROUP BY 1, 2
), starters AS (
    SELECT l.game_id, l.club_id, count(*) AS starters,
           count(*) FILTER (WHERE a.player_id IS NULL) AS starters_without_app
    FROM lineup l LEFT JOIN raw_appearances a USING (game_id, player_id)
    WHERE l.started GROUP BY 1, 2
), sides AS (
    SELECT game_id, competition_id, season, date, home_club_id AS club_id, away_club_id AS opp_id,
           TRUE AS is_home, home_club_goals AS goals_for, away_club_goals AS goals_against
    FROM raw_games
    UNION ALL
    SELECT game_id, competition_id, season, date, away_club_id, home_club_id,
           FALSE, away_club_goals, home_club_goals
    FROM raw_games
)
SELECT s.*,
       s.goals_for > s.goals_against AS won,
       coalesce(a.apps, 0) AS apps,
       coalesce(a.player_goals, 0) AS player_goals,
       coalesce(o.own_goals, 0) AS own_goals,
       coalesce(st.starters, 0) AS starters,
       coalesce(a.apps, 0) >= 11
         AND coalesce(a.player_goals, 0) + coalesce(o.own_goals, 0) = s.goals_for
         AND coalesce(st.starters_without_app, 0) = 0 AS trusted
FROM sides s
LEFT JOIN apps a USING (game_id, club_id)
LEFT JOIN own_goals o USING (game_id, club_id)
LEFT JOIN starters st USING (game_id, club_id)
WHERE s.goals_for IS NOT NULL AND s.goals_against IS NOT NULL;

CREATE TABLE league_coverage AS
SELECT g.competition_id, count(*) AS records,
       avg(CASE WHEN g.trusted THEN 1.0 ELSE 0.0 END) AS trust_share,
       avg(CASE WHEN g.trusted THEN 1.0 ELSE 0.0 END) >= {min_trust} AS player_level,
       min(g.date) AS first_game, max(g.date) AS last_game
FROM club_game g JOIN raw_competitions c USING (competition_id)
WHERE c.type = 'domestic_league' GROUP BY 1;

-- Running count of untrusted games per club and league: a streak must not span one.
CREATE TABLE untrusted_running AS
SELECT club_id, competition_id, date,
       sum(CASE WHEN trusted THEN 0 ELSE 1 END)
         OVER (PARTITION BY club_id, competition_id ORDER BY date, game_id) AS untrusted_so_far
FROM club_game;

CREATE TABLE appearance AS
SELECT a.game_id, a.player_id, a.player_club_id AS club_id, g.opp_id, g.competition_id, g.season,
       g.date, g.is_home, a.goals, a.goals > 0 AS scored, a.assists, a.minutes_played AS minutes,
       l.started
FROM raw_appearances a
JOIN club_game g ON g.game_id = a.game_id AND g.club_id = a.player_club_id
JOIN league_coverage c ON c.competition_id = g.competition_id AND c.player_level
LEFT JOIN lineup l ON l.game_id = a.game_id AND l.player_id = a.player_id
WHERE g.trusted AND a.minutes_played > 0;

CREATE TABLE player AS
SELECT player_id, name, position, sub_position, coalesce(highest_market_value_in_eur, 0) AS peak_value
FROM raw_players;

CREATE TABLE club AS
SELECT club_id, arg_max(name, date) AS name FROM (
    SELECT home_club_id AS club_id, home_club_name AS name, date FROM raw_games
    UNION ALL SELECT away_club_id, away_club_name, date FROM raw_games
) WHERE name IS NOT NULL GROUP BY 1;
"""


def build() -> None:
    download()
    DB_PATH.unlink(missing_ok=True)
    con = duckdb.connect(str(DB_PATH))
    for table in TABLES:
        con.execute(
            f"CREATE TABLE raw_{table} AS SELECT * FROM "
            f"read_csv_auto('{RAW_DIR / (table + '.csv.gz')}', sample_size=-1)"
        )
    con.execute(SCHEMA.format(min_trust=MIN_LEAGUE_TRUST))
    print("league                 records  trusted  player-level  period")
    for row in con.execute(
        "SELECT competition_id, records, trust_share, player_level, first_game, last_game "
        "FROM league_coverage ORDER BY player_level DESC, records DESC"
    ).fetchall():
        print(f"{row[0]:<20} {row[1]:>9}  {row[2]:>6.1%}  {str(row[3]):<12}  {row[4]} .. {row[5]}")
    print("appearances used:", con.execute("SELECT count(*) FROM appearance").fetchone()[0])
    con.close()


if __name__ == "__main__":
    build()
