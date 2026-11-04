"""Turn verified insights into feed cards. Writes data/feed.json.

The model only rewrites a fact that was already verified. Each text goes through rule checks
and then a judge that compares its meaning with the fact. A text that fails goes back with the
errors; if it keeps failing, the card keeps the plain verified fact.

Usage: python -m insights.write_feed [--limit 10]
"""
import argparse
import json
from collections import Counter
from collections.abc import Callable

import duckdb

from .checks import check_text
from .config import DB_PATH, FEED_PATH, LLM_MODEL, MAX_REWRITES, WRITTEN_FEED_PATH
from .llm import LLMError, complete

SYSTEM = """You are an editor at an English-language feed of football curiosities.
You receive a verified fact and rewrite it as a short, lively card for fans.

Strict rules:
- Use ONLY the information in the fact. Add nothing from your own knowledge: transfers, positions, managers, explanations.
- Every number stays exactly as in the fact and is written in digits, never in words. Dates stay in the format 11 Nov 2012.
- Keep the phrasing "X of Y" when the fact uses it, and do not swap the numbers.
- Each number stays attached to what it measures. A goal total belongs to the games with the named opponent, not to "the other games". A percentage of games is not a percentage of goals.
- For a streak, say clearly that the player scored in every one of the consecutive appearances.
- No superlatives ("best", "most"), no "record", "historic", "unique".
- No explanations of cause ("because", "thanks to"), and no "impact", "efficient" or other words that suggest a cause or a quality the fact does not state. The data shows what happened, not why.
- No "always", "all" or "never" unless the fact says exactly that.
- Keep words that mark an estimate, such as "about".
- Name the player as in the fact, and repeat the surname instead of using he, him, his, she or her. For clubs use the short common name in the Latin alphabet (for example Lokomotiv Moscow).
- Correct English. Title of at most 8 words, text of at most 2 sentences.

Style: write like a sports journalist telling a friend. The title states the idea, not just the names. Short, active sentences, no report language ("this rate is compared with").

Style example, with an invented player:
Fact: Ion Popescu scored in 9 of 12 league games against FC Example (75%), with 11 goals in those games. In the other games in the database the scoring rate is 20%.
Title: FC Example, Popescu's favourite opponent
Text: Popescu scored in 9 of 12 games against FC Example, 11 goals in all. Against everyone else the scoring rate drops to 20%."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {"title": {"type": "STRING"}, "text": {"type": "STRING"}},
    "required": ["title", "text"],
}

JUDGE_FLAGS = {
    "number_misattached": "A number is tied to something other than in the fact: a goal total placed on another group, a percentage of games presented as a percentage of goals, swapped groups.",
    "outside_context": "The card mentions something absent from the fact, such as the player's role, title or team, a transfer or an event. A short form of a club name from the fact does not count.",
    "implied_cause": "The card says or suggests someone produced the result (\"makes them win\", \"transforms the team\", \"thanks to\"). The fact only shows what happened.",
    "exaggeration": "An estimate is presented as certain, or the claim is stronger than the fact.",
    "streak_unclear": "The fact describes a run of consecutive appearances with a goal, but the card does not make clear the player scored in every one of them. \"24 goals in 15 consecutive appearances\" does NOT say that. If the fact does not describe a run, the answer is false.",
}

JUDGE_SYSTEM = (
    "You compare a feed card with the verified fact it was written from.\n"
    "Answer each question separately: true means the problem exists in the card.\n\n"
    + "\n".join(f"{name}: {question}" for name, question in JUDGE_FLAGS.items())
    + "\n\nLeaving out secondary details, rephrasing and a lively tone are not problems.\n"
    "In \"problem\" write briefly what is wrong, or an empty string if nothing is."
)

JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {**{name: {"type": "BOOLEAN"} for name in JUDGE_FLAGS}, "problem": {"type": "STRING"}},
    "required": [*JUDGE_FLAGS, "problem"],
}


def judge_text(fact: str, title: str, text: str, ask: Callable = complete) -> list[str]:
    """Return what is wrong with the meaning of a card. Empty means the judge accepts it."""
    answer = ask(JUDGE_SYSTEM, f"Verified fact:\n{fact}\n\nCard:\n{title}\n{text}", JUDGE_SCHEMA)
    flagged = [name for name in JUDGE_FLAGS if answer[name]]
    return [f"meaning changed ({', '.join(flagged)}): {answer['problem']}"] if flagged else []


FALLBACK_TITLES = {
    "opponent_hot": "A favourite opponent", "opponent_cold": "The club that holds out",
    "home_away": "Home and away", "scoring_streak": "A scoring run",
    "super_sub": "Off the bench", "recent_form": "In form",
    "team_head_to_head": "A one-sided fixture", "with_without": "With and without",
}


def subject_name(con, insight: dict) -> str | None:
    if insight["subject_type"] != "player":
        return None  # club names may legitimately be shortened
    return con.execute("SELECT name FROM player WHERE player_id = ?", [insight["subject_id"]]).fetchone()[0]


def write_card(insight: dict, name: str | None, ask: Callable = complete, judge: Callable = judge_text) -> dict:
    """Return a card. `written_by` says whether the model's text passed the checks."""
    prompt = f"Verified fact:\n{insight['fact']}"
    errors: list[str] = []
    for attempt in range(MAX_REWRITES + 1):
        full_prompt = prompt if not errors else f"{prompt}\n\nThe previous attempt was rejected:\n- " + "\n- ".join(errors)
        try:
            answer = ask(SYSTEM, full_prompt, SCHEMA)
            title, text = answer["title"].strip(), answer["text"].strip()
            errors = check_text(f"{title}\n{text}", insight, name)
            if not errors:
                errors = judge(insight["fact"], title, text)
        except (LLMError, KeyError, AttributeError) as error:
            return _card(insight, FALLBACK_TITLES[insight["kind"]], insight["fact"], "template", attempt, [str(error)])
        if not errors:
            return _card(insight, title, text, "llm", attempt, [])
    return _card(insight, FALLBACK_TITLES[insight["kind"]], insight["fact"], "template", MAX_REWRITES, errors)


def _card(insight, title, text, written_by, rewrites, errors) -> dict:
    return {
        "title": title, "text": text, "tier": insight["tier"], "kind": insight["kind"],
        "written_by": written_by, "rewrites": rewrites, "rejected_because": errors,
        "verified_fact": insight["fact"], "score": insight["score"],
        "numbers": insight["numbers"], "evidence": insight["evidence"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    source = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    con = duckdb.connect(str(DB_PATH), read_only=True)
    cards = []
    for insight in source["insights"][: args.limit]:
        card = write_card(insight, subject_name(con, insight))
        cards.append(card)
        print(f"[{card['written_by']}/{card['rewrites']}] {card['title']} — {card['text']}", flush=True)
    WRITTEN_FEED_PATH.write_text(json.dumps(
        {"data_as_of": source["data_as_of"], "model": LLM_MODEL, "cards": cards}, ensure_ascii=False, indent=1,
    ), encoding="utf-8")
    print(f"\n{len(cards)} cards:", dict(Counter(c["written_by"] for c in cards)),
          "first-try:", sum(c["written_by"] == "llm" and c["rewrites"] == 0 for c in cards))
    for card in cards:
        if card["written_by"] == "template":
            print("FELL BACK:", card["verified_fact"][:80], card["rejected_because"])


if __name__ == "__main__":
    main()
