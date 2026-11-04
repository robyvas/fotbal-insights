"""Insight generators. Each one tests EVERY candidate combination, corrects for how many it
tested, and only then keeps the ones with a large enough effect.

Tiers shown in the feed:
  confirmed  survives the false-discovery correction: unlikely to be luck.
  record     rare in absolute terms among all players (see RECORD_STREAK_MIN).
  notable    true and striking, but with this many tests it could still be luck.

Each returned insight carries `evidence`: groups of game ids plus the counts they must
reproduce. verify.py recounts those from the raw tables, independently of this code.
"""
import numpy as np

from . import stats as st
from .config import FDR, RECORD_STREAK_MIN


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _n(count: int, plural: str, singular: str) -> str:
    return f"1 {singular}" if count == 1 else f"{count} {plural}"


def _keep(rows, p_values, min_effect=None, notable_p=None):
    """Adjust p-values over all tested rows. Returns ([(row, p, adjusted, tier)], tested)."""
    adjusted = st.benjamini_hochberg(p_values)
    survivors = []
    for row, p, adj in zip(rows, p_values, adjusted):
        if min_effect is not None and not min_effect(row):
            continue
        if adj < FDR:
            survivors.append((row, float(p), float(adj), "confirmed"))
        elif notable_p is not None and p < notable_p:
            survivors.append((row, float(p), float(adj), "notable"))
    return survivors, len(rows)


def _insight(kind, subject_type, subject_id, p, adj, tier, tested, fact, numbers, evidence):
    return {
        "kind": kind, "subject_type": subject_type, "subject_id": int(subject_id),
        "tier": tier, "p_value": p, "adjusted_p": adj, "candidates_tested": tested,
        "fact": fact, "numbers": numbers, "evidence": evidence,
    }


def _scored(player_id, game_ids, k):
    return {"metric": "scored", "player_id": int(player_id), "game_ids": list(game_ids), "k": int(k), "n": len(game_ids)}


def _goals(player_id, game_ids, k):
    return {"metric": "goals", "player_id": int(player_id), "game_ids": list(game_ids), "k": int(k), "n": len(game_ids)}


def _won(club_id, game_ids, k):
    return {"metric": "won", "club_id": int(club_id), "game_ids": list(game_ids), "k": int(k), "n": len(game_ids)}


PAIR_SQL = """
WITH pair AS (
    SELECT player_id, opp_id, count(*) n, sum(scored::INT) k, sum(goals) goals, list(game_id ORDER BY date) ids
    FROM appearance GROUP BY 1, 2 HAVING count(*) >= {min_n}
), career AS (
    SELECT player_id, count(*) n_all, sum(scored::INT) k_all FROM appearance GROUP BY 1
)
SELECT p.player_id, pl.name, p.opp_id, cl.name, p.n, p.k, p.goals, c.n_all - p.n, c.k_all - p.k, p.ids
FROM pair p JOIN career c USING (player_id) JOIN player pl USING (player_id) JOIN club cl ON cl.club_id = p.opp_id
WHERE c.n_all - p.n >= 30 AND c.k_all > p.k
"""


def opponent_hot(con):
    """A player scores far more often against one club than against everyone else."""
    # Only regular scorers. Rest-of-career rate does not depend on this pair, so filtering
    # on it before testing does not bias the correction.
    rows = [r for r in con.execute(PAIR_SQL.format(min_n=8)).fetchall() if r[8] / r[7] >= 0.15]
    if not rows:
        return [], 0
    k = np.array([r[5] for r in rows])
    n = np.array([r[4] for r in rows])
    base = np.array([r[8] / r[7] for r in rows])
    p = st.binom_upper(k, n, base)
    kept, tested = _keep(rows, p, lambda r: r[5] / r[4] - r[8] / r[7] >= 0.25 and r[5] >= 5, notable_p=1e-3)
    out = []
    for r, pv, adj, tier in kept:
        pid, name, _, opp, n_, k_, goals, n_rest, k_rest, ids = r
        rate, baseline = k_ / n_, k_rest / n_rest
        fact = (f"{name} scored in {k_} of {_n(n_, 'league games', 'league game')} against {opp} ({_pct(rate)}), "
                f"with {_n(goals, 'goals', 'goal')} in those games. In the other games in the database the scoring rate is {_pct(baseline)}.")
        out.append(_insight("opponent_hot", "player", pid, pv, adj, tier, tested, fact,
                            {"k": k_, "n": n_, "goals": goals, "rate": rate, "baseline": baseline, "opponent": opp},
                            [_scored(pid, ids, k_)]))
    return out, tested


def opponent_cold(con):
    """A regular scorer has never scored against one specific club."""
    rows = [r for r in con.execute(PAIR_SQL.format(min_n=10)).fetchall() if r[8] / r[7] >= 0.30]
    if not rows:
        return [], 0
    k = np.array([r[5] for r in rows])
    n = np.array([r[4] for r in rows])
    base = np.array([r[8] / r[7] for r in rows])
    p = st.binom_lower(k, n, base)
    kept, tested = _keep(rows, p, lambda r: r[5] == 0, notable_p=0.02)
    out = []
    for r, pv, adj, tier in kept:
        pid, name, _, opp, n_, _, _, n_rest, k_rest, ids = r
        baseline = k_rest / n_rest
        fact = (f"{name} has never scored against {opp} in {_n(n_, 'league games', 'league game')} (0 of {n_}), "
                f"despite scoring in {_pct(baseline)} of the other games in the database.")
        out.append(_insight("opponent_cold", "player", pid, pv, adj, tier, tested, fact,
                            {"k": 0, "n": n_, "baseline": baseline, "opponent": opp}, [_scored(pid, ids, 0)]))
    return out, tested


def home_away(con):
    """A player's home/away split differs from the normal home advantage across all players."""
    home_rate, away_rate = con.execute(
        "SELECT avg(scored::INT) FILTER (WHERE is_home), avg(scored::INT) FILTER (WHERE NOT is_home) FROM appearance"
    ).fetchone()
    rows = con.execute("""
        SELECT a.player_id, p.name,
               count(*) FILTER (WHERE is_home) nh, sum(scored::INT) FILTER (WHERE is_home) kh,
               count(*) FILTER (WHERE NOT is_home) na, sum(scored::INT) FILTER (WHERE NOT is_home) ka,
               list(game_id) FILTER (WHERE is_home) ih, list(game_id) FILTER (WHERE NOT is_home) ia
        FROM appearance a JOIN player p USING (player_id) GROUP BY 1, 2
        HAVING nh >= 30 AND na >= 30 AND sum(scored::INT) > 0
    """).fetchall()
    if not rows:
        return [], 0
    nh, kh = np.array([r[2] for r in rows]), np.array([r[3] for r in rows])
    na, ka = np.array([r[4] for r in rows]), np.array([r[5] for r in rows])
    # With the normal home advantage, this share of the player's scoring games would be at home.
    share = nh * home_rate / (nh * home_rate + na * away_rate)
    p = st.binom_two_sided(kh, kh + ka, share)
    kept, tested = _keep(rows, p, lambda r: abs(r[3] / r[2] - r[5] / r[4]) >= 0.15, notable_p=0.005)
    out = []
    for r, pv, adj, tier in kept:
        pid, name, nh_, kh_, na_, ka_, ih, ia = r
        rh, ra = kh_ / nh_, ka_ / na_
        where = "away" if ra > rh else "at home"
        fact = (f"{name} scores far more often {where}: "
                f"at home in {kh_} of {_n(nh_, 'games', 'game')} ({_pct(rh)}), away in {ka_} of {na_} ({_pct(ra)}).")
        out.append(_insight("home_away", "player", pid, pv, adj, tier, tested, fact,
                            {"kh": kh_, "nh": nh_, "ka": ka_, "na": na_, "rate_home": rh, "rate_away": ra},
                            [_scored(pid, ih, kh_), _scored(pid, ia, ka_)]))
    return out, tested


def scoring_streak(con):
    """Longest run of league appearances with a goal, for one player at one club.

    The run breaks at a non-scoring appearance and at any untrusted game of that club,
    since we cannot know whether the player scored there.
    """
    rows = con.execute("""
        WITH seq AS (
            SELECT a.*, u.untrusted_so_far,
                   lag(u.untrusted_so_far) OVER w AS prev_untrusted
            FROM appearance a
            JOIN (SELECT DISTINCT club_id, competition_id, date, max(untrusted_so_far) OVER (PARTITION BY club_id, competition_id, date) AS untrusted_so_far
                  FROM untrusted_running) u USING (club_id, competition_id, date)
            WINDOW w AS (PARTITION BY a.player_id, a.club_id, a.competition_id ORDER BY a.date, a.game_id)
        ), marked AS (
            SELECT *, sum(CASE WHEN NOT scored OR untrusted_so_far IS DISTINCT FROM coalesce(prev_untrusted, untrusted_so_far) THEN 1 ELSE 0 END)
                      OVER (PARTITION BY player_id, club_id, competition_id ORDER BY date, game_id) AS run_id
            FROM seq
        ), runs AS (
            SELECT player_id, club_id, competition_id, run_id, count(*) len, sum(goals) goals,
                   min(date) d1, max(date) d2, list(game_id ORDER BY date) ids
            FROM marked WHERE scored GROUP BY 1, 2, 3, 4
        ), best AS (
            SELECT * FROM runs QUALIFY row_number() OVER (PARTITION BY player_id ORDER BY len DESC, d1) = 1
        ), career AS (
            SELECT player_id, count(*) n_all, sum(scored::INT) k_all FROM appearance GROUP BY 1
        )
        SELECT b.player_id, p.name, cl.name, b.competition_id, b.len, b.goals, b.d1, b.d2, c.n_all, c.k_all, b.ids
        FROM best b JOIN career c USING (player_id) JOIN player p USING (player_id) JOIN club cl ON cl.club_id = b.club_id
        WHERE c.n_all - b.len >= 30
    """).fetchall()
    if not rows:
        return [], 0
    length = np.array([r[4] for r in rows])
    n = np.array([r[8] for r in rows])
    # Whole-career rate, run included: never zero, and conservative for the player.
    base = np.array([r[9] / r[8] for r in rows])
    p = st.run_probability(length, n, base)
    adjusted = st.benjamini_hochberg(p)
    kept, tested = [], len(rows)
    for r, pv, adj in zip(rows, p, adjusted):
        if adj < FDR and r[4] >= 6:
            kept.append((r, float(pv), float(adj), "confirmed"))
        elif r[4] >= RECORD_STREAK_MIN:
            # For a prolific scorer a long run is not improbable, but it is rare
            # among players: measure that with the share of players who reached it.
            share = float((length >= r[4]).mean())
            kept.append((r, share, share, "record"))
    out = []
    for r, pv, adj, tier in kept:
        pid, name, club, comp, len_, goals, d1, d2, n_all, k_all, ids = r
        baseline = (k_all - len_) / (n_all - len_)
        fact = (f"{name} scored in {_n(len_, 'consecutive league appearances', 'league appearance')} for {club} "
                f"({d1:%d %b %Y} – {d2:%d %b %Y}), {_n(goals, 'goals', 'goal')} in total. "
                f"In the other games in the database the scoring rate is {_pct(baseline)}.")
        out.append(_insight("scoring_streak", "player", pid, pv, adj, tier, tested, fact,
                            {"length": len_, "goals": goals, "baseline": baseline, "competition": comp,
                             "from": str(d1), "to": str(d2), "club": club},
                            [_scored(pid, ids, len_)]))
    return out, tested


def super_sub(con):
    """Scores more per 90 minutes coming off the bench than when starting."""
    # Everyone scores more per minute off the bench, because game endings are more open.
    # Compare each player with that general ratio, not with the starter rate alone.
    bench_boost = con.execute("""
        SELECT (sum(goals) FILTER (WHERE NOT started) * 1.0 / sum(minutes) FILTER (WHERE NOT started))
             / (sum(goals) FILTER (WHERE started) * 1.0 / sum(minutes) FILTER (WHERE started))
        FROM appearance WHERE started IS NOT NULL
    """).fetchone()[0]
    rows = con.execute("""
        SELECT a.player_id, p.name,
               count(*) FILTER (WHERE NOT started) ns, sum(goals) FILTER (WHERE NOT started) gs, sum(minutes) FILTER (WHERE NOT started) ms,
               count(*) FILTER (WHERE started) nt, sum(goals) FILTER (WHERE started) gt, sum(minutes) FILTER (WHERE started) mt,
               list(game_id) FILTER (WHERE NOT started) ids_sub, list(game_id) FILTER (WHERE started) ids_start
        FROM appearance a JOIN player p USING (player_id) WHERE started IS NOT NULL GROUP BY 1, 2
        HAVING ns >= 20 AND mt >= 1000 AND gt > 0
    """).fetchall()
    if not rows:
        return [], 0
    gs = np.array([r[3] or 0 for r in rows])
    mu = np.array([r[6] / r[7] * r[4] * bench_boost for r in rows])
    p = st.poisson_upper(gs, mu)
    kept, tested = _keep(rows, p, lambda r: (r[3] or 0) >= 5 and (r[3] or 0) / r[4] >= 1.5 * bench_boost * r[6] / r[7])
    out = []
    for r, pv, adj, tier in kept:
        pid, name, ns, gs_, ms, nt, gt, mt, ids_sub, ids_start = r
        per90_sub, per90_start = gs_ / ms * 90, gt / mt * 90
        fact = (f"{name} scores more often off the bench: {_n(gs_, 'goals', 'goal')} in {ms} minutes as a substitute "
                f"({per90_sub:.2f} per 90 minutes), against {_n(gt, 'goals', 'goal')} in {mt} minutes as a starter ({per90_start:.2f}).")
        out.append(_insight("super_sub", "player", pid, pv, adj, tier, tested, fact,
                            {"goals_sub": gs_, "minutes_sub": ms, "goals_start": gt, "minutes_start": mt,
                             "per90_sub": per90_sub, "per90_start": per90_start, "general_bench_boost": bench_boost},
                            [_goals(pid, ids_sub, gs_), _goals(pid, ids_start, gt)]))
    return out, tested


def recent_form(con):
    """Last 10 league appearances versus the player's own earlier scoring rate."""
    cutoff = con.execute("SELECT max(date) - INTERVAL 120 DAY FROM appearance").fetchone()[0]
    rows = con.execute("""
        WITH ranked AS (
            SELECT *, row_number() OVER (PARTITION BY player_id ORDER BY date DESC, game_id DESC) rn FROM appearance
        )
        SELECT r.player_id, p.name,
               sum(goals) FILTER (WHERE rn <= 10) g10, sum(minutes) FILTER (WHERE rn <= 10) m10,
               sum(goals) FILTER (WHERE rn > 10) g_prev, sum(minutes) FILTER (WHERE rn > 10) m_prev,
               max(date) last_game, list(game_id) FILTER (WHERE rn <= 10) ids
        FROM ranked r JOIN player p USING (player_id) GROUP BY 1, 2
        HAVING count(*) >= 40 AND sum(goals) FILTER (WHERE rn > 10) > 0 AND max(date) >= ?
    """, [cutoff]).fetchall()
    if not rows:
        return [], 0
    g10 = np.array([r[2] for r in rows])
    mu = np.array([r[4] / r[5] * r[3] for r in rows])
    p = st.poisson_upper(g10, mu)
    kept, tested = _keep(rows, p, lambda r: r[2] >= 6 and r[2] / r[3] >= 2 * r[4] / r[5], notable_p=1e-3)
    out = []
    for r, pv, adj, tier in kept:
        pid, name, g10_, m10, g_prev, m_prev, last_game, ids = r
        expected = g_prev / m_prev * m10
        fact = (f"{name} has {_n(g10_, 'goals', 'goal')} in the last 10 league appearances (up to {last_game:%d %b %Y}). "
                f"At the earlier rate, the expected total would be about {expected:.1f}.")
        out.append(_insight("recent_form", "player", pid, pv, adj, tier, tested, fact,
                            {"goals": g10_, "minutes": m10, "expected": expected, "last_game": str(last_game)},
                            [_goals(pid, ids, g10_)]))
    return out, tested


def team_head_to_head(con):
    """A club wins far more often against one opponent than against everyone else."""
    rows = con.execute("""
        WITH league AS (
            SELECT g.* FROM club_game g JOIN league_coverage USING (competition_id)
        ), pair AS (
            SELECT club_id, opp_id, count(*) n, sum(won::INT) k, min(date) d1, max(date) d2,
                   list(game_id ORDER BY date) ids, mode(competition_id) comp
            FROM league GROUP BY 1, 2 HAVING count(*) >= 8
        ), total AS (SELECT club_id, count(*) n_all, sum(won::INT) k_all FROM league GROUP BY 1)
        SELECT p.club_id, c1.name, p.opp_id, c2.name, p.n, p.k, t.n_all - p.n, t.k_all - p.k, p.d1, p.d2, p.ids, p.comp
        FROM pair p JOIN total t USING (club_id) JOIN club c1 ON c1.club_id = p.club_id JOIN club c2 ON c2.club_id = p.opp_id
        WHERE t.n_all - p.n >= 30 AND t.k_all > p.k
    """).fetchall()
    if not rows:
        return [], 0
    k = np.array([r[5] for r in rows])
    n = np.array([r[4] for r in rows])
    base = np.array([r[7] / r[6] for r in rows])
    p = st.binom_upper(k, n, base)
    kept, tested = _keep(rows, p, lambda r: r[5] / r[4] - r[7] / r[6] >= 0.25, notable_p=1e-3)
    out = []
    for r, pv, adj, tier in kept:
        cid, name, _, opp, n_, k_, n_rest, k_rest, d1, d2, ids, comp = r
        rate, baseline = k_ / n_, k_rest / n_rest
        fact = (f"{name} won {k_} of {_n(n_, 'league games', 'league game')} against {opp} ({_pct(rate)}), "
                f"against {_pct(baseline)} versus other clubs ({d1.year}–{d2.year}).")
        out.append(_insight("team_head_to_head", "club", cid, pv, adj, tier, tested, fact,
                            {"k": k_, "n": n_, "rate": rate, "baseline": baseline, "opponent": opp, "competition": comp},
                            [_won(cid, ids, k_)]))
    return out, tested


def with_without(con):
    """A club's win rate with a player in the starting XI versus without.

    "Without" only counts games between the player's first and last start of that season,
    otherwise games from before signing would count as absence. This is an association,
    not a cause: rotation and injuries also vary with the opponent.
    """
    rows = con.execute("""
        WITH games AS (
            SELECT g.game_id, g.club_id, g.season, g.date, g.won FROM club_game g
            JOIN league_coverage c ON c.competition_id = g.competition_id AND c.player_level
            WHERE g.starters >= 11
        ), starts AS (
            SELECT l.game_id, l.player_id, g.club_id, g.season, g.date FROM lineup l
            JOIN games g ON g.game_id = l.game_id AND g.club_id = l.club_id WHERE l.started
        ), seasons AS (
            SELECT player_id, club_id, season, min(date) first_start, max(date) last_start
            FROM starts GROUP BY 1, 2, 3 HAVING count(*) >= 10
        ), joined AS (
            SELECT s.player_id, s.club_id, g.game_id, g.won, st.game_id IS NOT NULL AS started
            FROM seasons s JOIN games g ON g.club_id = s.club_id AND g.season = s.season
                 AND g.date BETWEEN s.first_start AND s.last_start
            LEFT JOIN starts st ON st.game_id = g.game_id AND st.player_id = s.player_id
        )
        SELECT j.player_id, p.name, j.club_id, c.name,
               count(*) FILTER (WHERE started) n1, sum(won::INT) FILTER (WHERE started) k1,
               count(*) FILTER (WHERE NOT started) n2, sum(won::INT) FILTER (WHERE NOT started) k2,
               list(game_id) FILTER (WHERE started) i1, list(game_id) FILTER (WHERE NOT started) i2
        FROM joined j JOIN player p USING (player_id) JOIN club c ON c.club_id = j.club_id
        GROUP BY 1, 2, 3, 4 HAVING n1 >= 30 AND n2 >= 15
    """).fetchall()
    if not rows:
        return [], 0
    n1, k1 = np.array([r[4] for r in rows]), np.array([r[5] for r in rows])
    n2, k2 = np.array([r[6] for r in rows]), np.array([r[7] for r in rows])
    p = st.fisher_upper(k1, n1, k2, n2)
    kept, tested = _keep(rows, p, lambda r: r[5] / r[4] - r[7] / r[6] >= 0.25, notable_p=1e-3)
    out = []
    for r, pv, adj, tier in kept:
        pid, name, cid, club, n1_, k1_, n2_, k2_, i1, i2 = r
        r1, r2 = k1_ / n1_, k2_ / n2_
        fact = (f"{club} won {_pct(r1)} of league games with {name} starting ({k1_} of {n1_}), "
                f"against {_pct(r2)} without {name} starting ({k2_} of {n2_}), over the same period.")
        out.append(_insight("with_without", "player", pid, pv, adj, tier, tested, fact,
                            {"k_with": k1_, "n_with": n1_, "k_without": k2_, "n_without": n2_,
                             "rate_with": r1, "rate_without": r2, "club": club},
                            [_won(cid, i1, k1_), _won(cid, i2, k2_)]))
    return out, tested


GENERATORS = [opponent_hot, opponent_cold, home_away, scoring_streak, super_sub,
              recent_form, team_head_to_head, with_without]
