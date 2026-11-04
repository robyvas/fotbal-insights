import pytest
from fastapi.testclient import TestClient

from insights.api import app, feed, stat_and_bars
from insights.config import WRITTEN_FEED_PATH


@pytest.fixture(scope="module")
def client():
    if not WRITTEN_FEED_PATH.exists():
        pytest.skip("run `python -m insights.write_feed` first")
    return TestClient(app)


def test_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Fotbal Verificat" in response.text


def test_feed_lists_every_card_without_exposing_internals(client):
    data = client.get("/api/feed").json()
    assert len(data["cards"]) == len(feed()["cards"])
    assert data["data_as_of"]
    assert "evidence" not in data["cards"][0]


def test_big_numbers_come_from_the_verified_numbers(client):
    for card in feed()["cards"]:
        stat, bars = stat_and_bars(card)
        assert stat["value"]
        for bar in bars:
            assert 0 <= bar["value"] <= bar["scale"], card["title"]
            assert bar["scale"] > 0


def test_mane_stat_is_right(client):
    card = next(c for c in feed()["cards"] if c["kind"] == "opponent_hot" and "Mané" in c["verified_fact"])
    stat, bars = stat_and_bars(card)
    assert stat["value"] == "12 din 14"
    assert [b["display"] for b in bars] == ["86%", "32%"]


def test_streak_label_uses_romanian_numeral_agreement(client):
    card = next(c for c in feed()["cards"] if c["kind"] == "scoring_streak" and "Messi" in c["verified_fact"])
    assert stat_and_bars(card)[0]["label"] == "apariții la rând cu gol, 33 de goluri"


def test_every_card_has_a_proof_that_recounts(client):
    for card_id in range(len(feed()["cards"])):
        proof = client.get(f"/api/cards/{card_id}/evidence").json()
        assert proof["groups"]
        for group in proof["groups"]:
            assert group["recount_ok"], group["recount_error"]
            assert len(group["rows"]) == group["n"]


def test_proof_rows_add_up_to_the_claim(client):
    cards = feed()["cards"]
    streak = next(i for i, c in enumerate(cards) if c["kind"] == "scoring_streak")
    group = client.get(f"/api/cards/{streak}/evidence").json()["groups"][0]
    assert all(row["goals"] > 0 for row in group["rows"])
    assert sum(row["goals"] > 0 for row in group["rows"]) == group["k"]


@pytest.mark.parametrize("bad_id", ["-1", "9999"])
def test_unknown_card_is_404(client, bad_id):
    assert client.get(f"/api/cards/{bad_id}/evidence").status_code == 404


def test_non_numeric_card_id_is_rejected(client):
    assert client.get("/api/cards/abc/evidence").status_code == 422
