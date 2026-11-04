"""Does the meaning judge catch wrong cards and accept right ones? Calls the real model.

Cases marked real-* are error types the writer actually produced and the rule checks let through.
Usage: python -m evals.judge_eval
"""
from insights.write_feed import judge_text

BARNES = ("Harvey Barnes scored in 6 of 8 league games against Leeds United (75%), with 7 goals in those games. "
          "In the other games in the database the scoring rate is 19%.")
YARMOLENKO = ("Andriy Yarmolenko scored in 10 of 13 league games against Chornomorets Odesa (77%), with 12 goals in those games. "
              "In the other games in the database the scoring rate is 29%.")
MANE = ("Sadio Mané scored in 12 of 14 league games against Crystal Palace (86%), with 13 goals in those games. "
        "In the other games in the database the scoring rate is 32%.")
GUIMARAES = ("Newcastle United won 52% of league games with Bruno Guimarães starting (76 of 145), "
             "against 11% without Bruno Guimarães starting (2 of 19), over the same period.")
GIBBS = ("Morgan Gibbs-White has 9 goals in the last 10 league appearances (up to 24 May 2026). "
         "At the earlier rate, the expected total would be about 1.5.")
LEWANDOWSKI = ("Robert Lewandowski scored in 15 consecutive league appearances for Bayern Munich "
               "(15 Feb 2021 – 18 Sep 2021), 24 goals in total. In the other games in the database the scoring rate is 55%.")
SON = ("Heung-min Son has never scored against Wolverhampton Wanderers in 12 league games, "
       "despite scoring in 30% of the other games in the database.")

# (name, fact, title, text, should the judge accept it)
CASES = [
    ("real-total-wrong-group", BARNES, "Barnes and Leeds", "Barnes scored in 6 of 8 games against Leeds United, or 75%. In the other games the rate is 19%, with 7 goals in total.", False),
    ("real-total-wrong-group-2", YARMOLENKO, "Yarmolenko and Chornomorets", "Yarmolenko scored in 10 of 13 games against Chornomorets Odesa, or 77%. In the other games in the database the rate is 29%, with 12 goals in total.", False),
    ("real-percent-of-what", MANE, "Mané and Crystal Palace", "Mané scored in 12 of 14 games against Crystal Palace, for a total of 13 goals, or 86%. In the other games the rate is 32%.", False),
    ("real-streak-unclear", LEWANDOWSKI, "Lewandowski at Bayern", "Robert Lewandowski scored 24 goals in 15 consecutive league appearances. Elsewhere the scoring rate is 55%.", False),
    ("groups-swapped", MANE, "Mané and Crystal Palace", "Mané scored in 32% of games against Crystal Palace. In the other games the rate rises to 86%.", False),
    ("implied-cause", GUIMARAES, "Bruno transforms Newcastle", "Bruno Guimarães makes Newcastle win: 52% when starting (76 of 145), 11% otherwise (2 of 19).", False),
    ("estimate-as-certain", GIBBS, "Gibbs-White in form", "Gibbs-White has 9 goals in the last 10 appearances. At the earlier rate the total would be exactly 1.5.", False),
    ("outside-context", SON, "Son and Wolves", "Son, the Tottenham captain, has never scored against Wolves in 12 games. Elsewhere the scoring rate is 30%.", False),
    ("good-mane", MANE, "Crystal Palace, Mané's favourite opponent", "Mané scored in 12 of 14 games against Crystal Palace, 13 goals in total. Against everyone else the scoring rate is 32%.", True),
    ("good-barnes", BARNES, "Barnes against Leeds", "Barnes scored in 6 of 8 games against Leeds United, or 75%, with 7 goals in those games. Elsewhere the rate is 19%.", True),
    ("good-streak", LEWANDOWSKI, "Lewandowski: 15 straight games with a goal", "Lewandowski scored in every one of 15 consecutive league appearances for Bayern, 24 goals in total. Elsewhere the scoring rate is 55%.", True),
    ("good-son", SON, "Wolves, the club Son cannot score against", "Son has never scored against Wolverhampton in 12 league games. Against other clubs the scoring rate is 30%.", True),
    ("good-guimaraes", GUIMARAES, "Newcastle with and without Bruno Guimarães", "Newcastle won 76 of 145 games with Bruno Guimarães starting (52%) and 2 of 19 without (11%).", True),
    ("good-gibbs", GIBBS, "Gibbs-White in form", "Gibbs-White has 9 goals in the last 10 league appearances. At the earlier rate the total would be about 1.5.", True),
]


def main() -> None:
    caught = missed = accepted = false_alarms = 0
    for name, fact, title, text, should_accept in CASES:
        problems = judge_text(fact, title, text)
        ok = not problems
        if should_accept:
            accepted += ok
            false_alarms += not ok
        else:
            caught += not ok
            missed += ok
        print(f"{'PASS' if ok == should_accept else 'FAIL'} {name}: {'accepted' if ok else problems[0]}")
    print(f"\nwrong cards caught {caught}/{caught + missed}, good cards accepted {accepted}/{accepted + false_alarms}")


if __name__ == "__main__":
    main()
