"""Rule checks on model-written text, against the verified fact it was written from.

These catch invented numbers, swapped "X din Y" pairs, numbers hidden in words, claims
the data cannot support, and dropped key numbers. They do NOT catch a change of meaning
that uses only allowed numbers, such as a total attached to the wrong group. That is the
job of the judge in write_feed.py, measured in evals/judge_eval.py.
"""
import re

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
PAIR = re.compile(r"(\d+)\s+din\s+(\d+)")

# "nouă" is left out because it also means "new" and "to us".
NUMBER_WORDS = re.compile(
    r"\b(doi|două|trei|patru|cinci|șase|șapte|opt|zece|\w+sprezece|\w+zeci|sută|sute|mie|mii"
    r"|jumătate|sfert|dublu|triplu|dublă|triplă|majoritatea)\b", re.IGNORECASE)

UNSUPPORTED_CLAIMS = re.compile(
    r"\b(cel mai|cea mai|cei mai|cele mai|record\w*|istoric\w*|unic\w*"
    r"|impact\w*|eficien\w*|eficac\w*|periculos\w*|precis|specialist\w*|ghinion\w*|datorită|din cauza|pentru că|fiindcă|deoarece|se datorează|secretul)\b", re.IGNORECASE)

# Absolute words are only true for a "never scored" fact.
ABSOLUTES = re.compile(r"\b(niciodată|niciun|nicio|mereu|întotdeauna|de fiecare dată|toate|toți)\b", re.IGNORECASE)

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
    fact = insight["fact_ro"]
    errors = []
    invented = _numbers(text) - _numbers(fact)
    if invented:
        errors.append(f"numere care nu apar în fapt: {sorted(invented)}")
    bad_pairs = set(PAIR.findall(text)) - set(PAIR.findall(fact))
    if bad_pairs:
        errors.append(f"perechi „X din Y” care nu apar în fapt: {sorted(bad_pairs)}")
    if match := NUMBER_WORDS.search(text):
        errors.append(f"numere scrise în cuvinte: „{match.group(0)}”; folosește cifre")
    if match := UNSUPPORTED_CLAIMS.search(text):
        errors.append(f"afirmație pe care datele nu o susțin: „{match.group(0)}”")
    if insight["kind"] != "opponent_cold" and (match := ABSOLUTES.search(text)):
        errors.append(f"cuvânt absolut nepermis: „{match.group(0)}”")
    present = _numbers(text)
    for key in REQUIRED_NUMBERS[insight["kind"]]:
        if str(insight["numbers"][key]) not in present:
            errors.append(f"lipsește numărul obligatoriu {insight['numbers'][key]}")
    if subject_name:
        surname = subject_name.split()[-1]
        if surname.lower() not in text.lower():
            errors.append(f"lipsește numele „{surname}”")
    return errors
