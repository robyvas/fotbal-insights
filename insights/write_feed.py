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

SYSTEM = """Ești editor la un feed românesc de curiozități din fotbal.
Primești un fapt verificat și îl rescrii ca un card scurt și viu, pentru fani.

Reguli stricte:
- Folosești DOAR informația din fapt. Nu adaugi context din ce știi tu: transferuri, poziții, antrenori, explicații.
- Toate numerele rămân exact ca în fapt și se scriu cu cifre, niciodată în cuvinte. Datele rămân în formatul zz.ll.aaaa.
- Păstrezi formularea „X din Y” când apare în fapt și nu inversezi numerele.
- Fără superlative („cel mai”), fără „record”, „istoric”, „unic”.
- Fără explicații ale cauzei („pentru că”, „datorită”). Datele arată ce s-a întâmplat, nu de ce.
- Fără „mereu”, „toate”, „niciodată”, decât dacă exact așa spune faptul.
- Numești jucătorul cu numele din fapt. Pentru cluburi folosești numele scurt uzual, în alfabet latin (de exemplu Lokomotiv Moscova).
- Fiecare număr rămâne lipit de ce măsoară. Totalul de goluri ține de meciurile cu adversarul numit, nu de „restul meciurilor”. Procentul de meciuri nu e procent de goluri.
- La o serie spui clar că a marcat în fiecare dintre aparițiile consecutive.
- Fără „impact”, „eficiență” sau alte cuvinte care sugerează o cauză sau o calitate pe care faptul nu o afirmă.
- Păstrezi cuvintele care arată o estimare, ca „cam”. Zecimalele se scriu cu virgulă: 1,5.
- Română corectă, cu diacritice. Titlu de maximum 8 cuvinte, text de maximum 2 propoziții.

Stil: scrii ca un jurnalist sportiv care povestește unui prieten. Titlul spune ideea, nu doar numele. Fraze scurte, active, fără limbaj de raport („această rată este comparată”, „acesta”).

Exemplu de stil, cu un jucător inventat:
Fapt: Ion Popescu a marcat în 9 din 12 meciuri de campionat împotriva echipei FC Exemplu (75%), față de 20% în restul meciurilor din baza de date.
Titlu: FC Exemplu, adversarul preferat al lui Popescu
Text: Popescu a marcat în 9 din 12 meciuri cu FC Exemplu, adică 75%. Împotriva celorlalte echipe ajunge doar la 20%."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {"title": {"type": "STRING"}, "text": {"type": "STRING"}},
    "required": ["title", "text"],
}

JUDGE_FLAGS = {
    "number_misattached": "Un număr e legat de altceva decât în fapt: un total de goluri pus la alt grup, un procent de meciuri prezentat ca procent de goluri, grupuri inversate.",
    "outside_context": "Cardul menționează ceva ce nu apare deloc în fapt, de exemplu rolul, funcția sau echipa jucătorului, un transfer ori un eveniment. Numele scurt al unui club din fapt nu se pune.",
    "implied_cause": "Cardul spune sau sugerează că cineva a produs rezultatul („o face să câștige”, „schimbă echipa”, „datorită lui”). Faptul arată doar ce s-a întâmplat.",
    "exaggeration": "O estimare e prezentată ca sigură sau afirmația e mai tare decât faptul.",
    "streak_unclear": "Faptul descrie o serie de apariții consecutive cu gol, dar din card nu reiese că a marcat în fiecare dintre ele. „24 de goluri în 15 apariții consecutive” NU spune asta. Dacă faptul nu descrie o serie, răspunsul e false.",
}

JUDGE_SYSTEM = (
    "Compari un card de feed cu faptul verificat din care a fost scris.\n"
    "Răspunzi separat la fiecare întrebare: true înseamnă că problema există în card.\n\n"
    + "\n".join(f"{name}: {question}" for name, question in JUDGE_FLAGS.items())
    + "\n\nOmisiunea unor detalii secundare, reformularea și tonul viu nu sunt probleme.\n"
    "În „problem” scrii scurt ce e greșit, sau un text gol dacă nu e nimic greșit."
)

JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {**{name: {"type": "BOOLEAN"} for name in JUDGE_FLAGS}, "problem": {"type": "STRING"}},
    "required": [*JUDGE_FLAGS, "problem"],
}


def judge_text(fact: str, title: str, text: str, ask: Callable = complete) -> list[str]:
    """Return what is wrong with the meaning of a card. Empty means the judge accepts it."""
    answer = ask(JUDGE_SYSTEM, f"Fapt verificat:\n{fact}\n\nCard:\n{title}\n{text}", JUDGE_SCHEMA)
    flagged = [name for name in JUDGE_FLAGS if answer[name]]
    return [f"sens schimbat ({', '.join(flagged)}): {answer['problem']}"] if flagged else []


FALLBACK_TITLES = {
    "opponent_hot": "Adversarul preferat", "opponent_cold": "Adversarul care îi rezistă",
    "home_away": "Acasă și în deplasare", "scoring_streak": "Serie de goluri",
    "super_sub": "De pe bancă", "recent_form": "Formă bună",
    "team_head_to_head": "Duel dezechilibrat", "with_without": "Cu el și fără el",
}


def subject_name(con, insight: dict) -> str | None:
    if insight["subject_type"] != "player":
        return None  # club names may legitimately be shortened
    return con.execute("SELECT name FROM player WHERE player_id = ?", [insight["subject_id"]]).fetchone()[0]


def write_card(insight: dict, name: str | None, ask: Callable = complete, judge: Callable = judge_text) -> dict:
    """Return a card. `written_by` says whether the model's text passed the checks."""
    prompt = f"Fapt verificat:\n{insight['fact_ro']}"
    errors: list[str] = []
    for attempt in range(MAX_REWRITES + 1):
        full_prompt = prompt if not errors else f"{prompt}\n\nÎncercarea anterioară a fost respinsă:\n- " + "\n- ".join(errors)
        try:
            answer = ask(SYSTEM, full_prompt, SCHEMA)
            title, text = answer["title"].strip(), answer["text"].strip()
            errors = check_text(f"{title}\n{text}", insight, name)
            if not errors:
                errors = judge(insight["fact_ro"], title, text)
        except (LLMError, KeyError, AttributeError) as error:
            return _card(insight, FALLBACK_TITLES[insight["kind"]], insight["fact_ro"], "template", attempt, [str(error)])
        if not errors:
            return _card(insight, title, text, "llm", attempt, [])
    return _card(insight, FALLBACK_TITLES[insight["kind"]], insight["fact_ro"], "template", MAX_REWRITES, errors)


def _card(insight, title, text, written_by, rewrites, errors) -> dict:
    return {
        "title": title, "text": text, "tier": insight["tier"], "kind": insight["kind"],
        "written_by": written_by, "rewrites": rewrites, "rejected_because": errors,
        "verified_fact": insight["fact_ro"], "score": insight["score"],
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
