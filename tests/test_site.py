import copy
import json

import duckdb
import pytest

from insights.build_site import SITE_FEED_PATH, build, proof_for, stat_and_bars
from insights.config import DB_PATH, ROOT, WRITTEN_FEED_PATH


@pytest.fixture(scope="module")
def source_cards():
    if not WRITTEN_FEED_PATH.exists() or not DB_PATH.exists():
        pytest.skip("run the pipeline first, see the README")
    return json.loads(WRITTEN_FEED_PATH.read_text(encoding="utf-8"))["cards"]


@pytest.fixture(scope="module")
def site(source_cards):
    return build()


def test_page_exists_and_loads_the_feed_by_relative_path():
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert "Football, Verified" in html
    assert 'fetch("feed.json")' in html
    assert "/api/" not in html


def test_site_has_every_card_without_internals(site, source_cards):
    assert len(site["cards"]) == len(source_cards)
    assert site["data_as_of"]
    assert "evidence" not in site["cards"][0]
    assert "rejected_because" not in site["cards"][0]


def test_big_numbers_stay_in_range(source_cards):
    for card in source_cards:
        stat, bars = stat_and_bars(card)
        assert stat["value"]
        for bar in bars:
            assert bar["scale"] > 0
            assert 0 <= bar["value"] <= bar["scale"], card["title"]


def test_mane_stat_is_right(source_cards):
    card = next(c for c in source_cards if c["kind"] == "opponent_hot" and "Mané" in c["verified_fact"])
    stat, bars = stat_and_bars(card)
    assert stat["value"] == "12 of 14"
    assert [b["display"] for b in bars] == ["86%", "32%"]


def test_streak_label(source_cards):
    card = next(c for c in source_cards if c["kind"] == "scoring_streak" and "Messi" in c["verified_fact"])
    assert stat_and_bars(card)[0]["label"] == "straight appearances with a goal, 33 goals in total"


def test_every_proof_has_a_row_per_claimed_game(site):
    for card in site["cards"]:
        assert card["proof"]["groups"]
        for group in card["proof"]["groups"]:
            assert len(group["rows"]) == group["n"]


def test_proof_rows_add_up_to_the_claim(site):
    for card in site["cards"]:
        for group in card["proof"]["groups"]:
            if group["metric"] == "scored":
                assert sum(r["goals"] > 0 for r in group["rows"]) == group["k"]
            elif group["metric"] == "goals":
                assert sum(r["goals"] for r in group["rows"]) == group["k"]
            else:
                assert sum(r["won"] for r in group["rows"]) == group["k"]


def test_build_stops_when_a_number_does_not_recount(source_cards):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    tampered = copy.deepcopy(source_cards[0])
    tampered["evidence"][0]["k"] += 1
    with pytest.raises(ValueError, match="recounted"):
        proof_for(con, tampered)
    con.close()


def test_published_feed_matches_a_fresh_build(site):
    if not SITE_FEED_PATH.exists():
        pytest.skip("run python -m insights.build_site first")
    assert json.loads(SITE_FEED_PATH.read_text(encoding="utf-8")) == json.loads(json.dumps(site))
