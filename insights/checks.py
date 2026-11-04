"""Rule checks on model-written text, against the verified fact it was written from.

These catch invented numbers, swapped "X of Y" pairs, numbers hidden in words, claims
the data cannot support, and dropped key numbers. They do NOT catch a change of meaning
that uses only allowed numbers, such as a total attached to the wrong group. That is the
job of the judge in write_feed.py, measured in evals/judge_eval.py.
"""
import re

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
PAIR = re.compile(r"(\d+)\s+of\s+(\d+)")

# "one" is left out because it is also a pronoun.
NUMBER_WORDS = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\w+teen|twenty|thirty|forty|fifty"
    r"|sixty|seventy|eighty|ninety|hundred|thousand|half|quarter|double|triple|twice|thrice|majority)\b",
    re.IGNORECASE)

UNSUPPORTED_CLAIMS = re.compile(
    r"\b(best|worst|most|least|greatest|record\w*|histor\w*|unique\w*"
    r"|impact\w*|effective\w*|efficien\w*|dangerous\w*|precise\w*|specialist\w*|unlucky|luck\w*|curse\w*|jinx\w*"
    r"|because|thanks to|due to|owing to|secret\w*)\b", re.IGNORECASE)

# Facts are written without gendered pronouns, and the cards keep to that.
PRONOUNS = re.compile(r"\b(he|him|his|she|her|hers)\b", re.IGNORECASE)

# Absolute words are allowed only when the fact itself uses them.
ABSOLUTES = re.compile(r"\b(never|always|all|every time|each time|without fail|not once)\b", re.IGNORECASE)

REQUIRED_NUMBERS = {
    "opponent_hot": ["k", "n"], "opponent_cold": ["n"], "home_away": ["kh", "nh", "ka", "na"],
    "scoring_streak": ["length", "goals"], "super_sub": ["goals_sub", "goals_start"],
    "recent_form": ["goals"], "team_head_to_head": ["k", "n"],
    "with_without": ["k_with", "n_with", "k_without", "n_without"],
}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER.findall(text)}


def check_text(text: str, insight: dict, subject_name: str | None = None) -> list[str]:
    """Return every rule the text breaks. An empty list means it passes."""
    fact = insight["fact"]
    errors = []
    invented = _numbers(text) - _numbers(fact)
    if invented:
        errors.append(f"numbers not in the fact: {sorted(invented)}")
    bad_pairs = set(PAIR.findall(text)) - set(PAIR.findall(fact))
    if bad_pairs:
        errors.append(f'"X of Y" pairs not in the fact: {sorted(bad_pairs)}')
    if match := NUMBER_WORDS.search(text):
        errors.append(f'number written as a word: "{match.group(0)}"; use digits')
    if match := UNSUPPORTED_CLAIMS.search(text):
        errors.append(f'claim the data does not support: "{match.group(0)}"')
    if match := PRONOUNS.search(text):
        errors.append(f'gendered pronoun: "{match.group(0)}"; repeat the surname')
    for match in ABSOLUTES.finditer(text):
        if match.group(0).lower() not in fact.lower():
            errors.append(f'absolute word not in the fact: "{match.group(0)}"')
    present = _numbers(text)
    for key in REQUIRED_NUMBERS[insight["kind"]]:
        if str(insight["numbers"][key]) not in present:
            errors.append(f"missing required number {insight['numbers'][key]}")
    if subject_name:
        surname = subject_name.split()[-1]
        if surname.lower() not in text.lower():
            errors.append(f'missing the name "{surname}"')
    return errors
