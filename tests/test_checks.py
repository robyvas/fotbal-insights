"""The checks and the rewrite loop, with a fake model: no network and no quota used."""
import pytest

from insights.checks import check_text
from insights.llm import LLMConfigError, LLMError
from insights.write_feed import JUDGE_FLAGS, judge_text
from insights.write_feed import write_card as real_write_card

ACCEPT = lambda *_: []  # noqa: E731


def write_card(insight, name, ask):
    return real_write_card(insight, name, ask, judge=ACCEPT)


MANE = {
    "kind": "opponent_hot", "tier": "notable", "score": 0.5,
    "fact": "Sadio Mané scored in 12 of 14 league games against Crystal Palace (86%), with 13 goals in those games. "
            "In the other games in the database the scoring rate is 32%.",
    "numbers": {"k": 12, "n": 14}, "evidence": [],
}
GOOD = "Mané scored in 12 of 14 games against Crystal Palace (86%), against 32% elsewhere."


def test_faithful_text_passes():
    assert check_text(GOOD, MANE, "Sadio Mané") == []


@pytest.mark.parametrize("text, expected", [
    ("Mané scored in 12 of 14 games against Palace, 15 goals.", "numbers not in the fact"),
    ("Mané scored in 14 of 12 games against Palace.", "pairs"),
    ("Mané scored in 12 of 14 games, three times as often.", "as a word"),
    ("Mané at the best: 12 of 14 games.", "does not support"),
    ("Mané scored in 12 of 14 games because Palace suits Mané.", "does not support"),
    ("Mané always scores: 12 of 14 games.", "absolute"),
    ("Mané scored often against Palace, 86%.", "missing required number"),
    ("The player scored in 12 of 14 games.", "missing the name"),
    ("The impact of Mané: 12 of 14 games.", "does not support"),
    ("Mané, the Palace specialist: 12 of 14 games.", "does not support"),
    ("Mané scored in 12 of 14 games and his rate is 86%.", "pronoun"),
])
def test_bad_text_is_rejected(text, expected):
    assert any(expected in error for error in check_text(text, MANE, "Sadio Mané"))


def test_decimal_comma_equals_decimal_point():
    insight = {"kind": "recent_form", "fact": "Gibbs-White has 9 goals. The expected total would be about 1.5.",
               "numbers": {"goals": 9}}
    assert check_text("Gibbs-White has 9 goals, not about 1,5.", insight, "Morgan Gibbs-White") == []


def test_absolute_word_is_allowed_only_when_the_fact_uses_it():
    cold = {"kind": "opponent_cold", "fact": "Son has never scored against Wolves in 12 league games.", "numbers": {"n": 12}}
    assert check_text("Son has never scored against Wolves in 12 games.", cold, "Heung-min Son") == []


def test_card_uses_text_that_passes_first_time():
    card = write_card(MANE, "Sadio Mané", lambda *_: {"title": "Mané and Palace", "text": GOOD})
    assert (card["written_by"], card["rewrites"], card["text"]) == ("llm", 0, GOOD)


def test_rejected_text_is_sent_back_with_the_error():
    prompts = []

    def fake(_system, prompt, _schema):
        prompts.append(prompt)
        return {"title": "Mané", "text": GOOD if len(prompts) == 2 else "Mané: 12 of 14 games, 99%."}

    card = write_card(MANE, "Sadio Mané", fake)
    assert (card["written_by"], card["rewrites"]) == ("llm", 1)
    assert "99" in prompts[1] and "rejected" in prompts[1]


def test_text_that_keeps_failing_falls_back_to_the_verified_fact():
    card = write_card(MANE, "Sadio Mané", lambda *_: {"title": "Mané", "text": "Mané: 99 goals."})
    assert card["written_by"] == "template"
    assert card["text"] == MANE["fact"]
    assert card["rejected_because"]


@pytest.mark.parametrize("answer", [{"wrong": "shape"}, {"title": None, "text": None}])
def test_malformed_answer_falls_back(answer):
    assert write_card(MANE, "Sadio Mané", lambda *_: answer)["written_by"] == "template"


def test_api_failure_falls_back():
    def broken(*_):
        raise LLMError("quota")

    assert write_card(MANE, "Sadio Mané", broken)["written_by"] == "template"


def test_configuration_error_stops_the_run():
    def wrong_model(*_):
        raise LLMConfigError("HTTP 404")

    with pytest.raises(LLMConfigError):
        write_card(MANE, "Sadio Mané", wrong_model)


def test_judge_rejection_sends_the_text_back_with_the_problem():
    prompts, verdicts = [], [["meaning changed: goals on the wrong group"], []]

    def fake(_system, prompt, _schema):
        prompts.append(prompt)
        return {"title": "Mané", "text": GOOD}

    card = real_write_card(MANE, "Sadio Mané", fake, judge=lambda *_: verdicts.pop(0))
    assert (card["written_by"], card["rewrites"]) == ("llm", 1)
    assert "wrong group" in prompts[1]


def test_text_the_judge_keeps_rejecting_falls_back():
    card = real_write_card(MANE, "Sadio Mané", lambda *_: {"title": "Mané", "text": GOOD},
                           judge=lambda *_: ["meaning changed"])
    assert card["written_by"] == "template"


def test_judge_failure_does_not_let_the_text_through():
    def broken(*_):
        raise LLMError("quota")

    card = real_write_card(MANE, "Sadio Mané", lambda *_: {"title": "Mané", "text": GOOD}, judge=broken)
    assert card["written_by"] == "template"


def test_judge_text_reads_each_flag():
    clean = dict.fromkeys(JUDGE_FLAGS, False) | {"problem": ""}
    assert judge_text("f", "t", "x", lambda *_: clean) == []
    flagged = judge_text("f", "t", "x", lambda *_: clean | {"implied_cause": True, "problem": "cause"})
    assert "implied_cause" in flagged[0] and "cause" in flagged[0]


def test_judge_answer_missing_a_flag_does_not_let_the_text_through():
    card = real_write_card(MANE, "Sadio Mané", lambda *_: {"title": "Mané", "text": GOOD},
                           judge=lambda f, t, x: judge_text(f, t, x, lambda *_: {"problem": ""}))
    assert card["written_by"] == "template"


def test_a_dropped_connection_is_retried_not_a_crash(monkeypatch):
    import insights.llm as llm

    calls = []

    def flaky(*_, **__):
        calls.append(1)
        raise ConnectionResetError("reset")

    monkeypatch.setattr(llm.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    monkeypatch.setattr(llm, "_api_key", lambda: "test")
    with pytest.raises(LLMError):
        llm._call("s", "p", {})
    assert len(calls) == llm.MAX_ATTEMPTS
