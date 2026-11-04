"""Generate, verify, score and rank insights. Writes data/insights.json.

Usage: python -m insights.run [--top 25]
"""
import argparse
import json
import math
from collections import Counter

import duckdb

from .config import (DB_PATH, FEED_PATH, RELEVANCE_WEIGHT, SURPRISE_CAP, SURPRISE_WEIGHT,
                     TEAM_RELEVANCE, TOP5)
from .generators import GENERATORS
from .verify import verify_insight


def relevance(con, insight) -> float:
    """How much people are likely to care, from 0 to 1."""
    if insight["subject_type"] == "player":
        value = con.execute("SELECT peak_value FROM player WHERE player_id = ?", [insight["subject_id"]]).fetchone()[0]
        # 1M EUR maps to 0, 150M EUR to 1, on a log scale.
        return min(1.0, max(0.0, (math.log10(max(value, 1)) - 6) / (math.log10(150e6) - 6)))
    comp = insight["numbers"].get("competition")
    if comp == "RO1":
        return TEAM_RELEVANCE["RO1"]
    return TEAM_RELEVANCE["top5"] if comp in TOP5 else TEAM_RELEVANCE["other"]


def score(con, insight) -> None:
    if insight["tier"] == "notable":
        # Did not survive the correction, so its raw improbability counts for half.
        strength = -math.log10(max(insight["p_value"], 1e-300)) / 2
    else:
        strength = -math.log10(max(insight["adjusted_p"], 1e-300))
    insight["surprise"] = min(1.0, strength / SURPRISE_CAP)
    insight["relevance"] = relevance(con, insight)
    insight["score"] = SURPRISE_WEIGHT * insight["surprise"] + RELEVANCE_WEIGHT * insight["relevance"]


def rank_for_feed(insights: list[dict]) -> list[dict]:
    """Greedy ranking that discounts repeats, so one player or one kind cannot fill the feed."""
    remaining, ranked = list(insights), []
    by_subject, by_kind = Counter(), Counter()
    while remaining:
        def adjusted(i):
            return i["score"] * 0.5 ** by_subject[i["subject_id"]] * 0.8 ** by_kind[i["kind"]]
        best = max(remaining, key=adjusted)
        remaining.remove(best)
        ranked.append(best)
        by_subject[best["subject_id"]] += 1
        by_kind[best["kind"]] += 1
    return ranked


def generate(con) -> tuple[list[dict], list[dict]]:
    insights, failures = [], []
    for generator in GENERATORS:
        found, tested = generator(con)
        ok = 0
        for insight in found:
            errors = verify_insight(con, insight)
            if errors:
                failures.append({"fact": insight["fact"], "errors": errors})
                continue
            score(con, insight)
            insights.append(insight)
            ok += 1
        print(f"{generator.__name__:<20} tested {tested:>7}  kept {len(found):>5}  verified {ok:>5}")
    return insights, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    insights, failures = generate(con)
    feed = rank_for_feed(insights)
    as_of = con.execute("SELECT max(date) FROM appearance").fetchone()[0]
    FEED_PATH.write_text(json.dumps({"data_as_of": str(as_of), "insights": feed}, ensure_ascii=False, indent=1, default=str))
    print(f"\n{len(feed)} insights, {len(failures)} failed verification, data as of {as_of}")
    print("by tier:", dict(Counter(i["tier"] for i in feed)))
    for failure in failures[:10]:
        print("FAILED:", failure)
    for i, insight in enumerate(feed[: args.top], 1):
        print(f"{i:>2}. [{insight['tier']}/{insight['kind']}] {insight['score']:.2f} {insight['fact']}")


if __name__ == "__main__":
    main()
