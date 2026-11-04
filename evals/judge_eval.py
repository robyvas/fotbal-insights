"""Does the meaning judge catch wrong cards and accept right ones? Calls the real model.

Cases marked real-* are errors the writer actually produced and the rule checks let through.
Usage: python -m evals.judge_eval
"""
from insights.write_feed import judge_text

BARNES = ("Harvey Barnes a marcat în 6 din 8 meciuri de campionat împotriva echipei Leeds United (75%), "
          "față de 19% în restul meciurilor din baza de date. 7 goluri în total.")
YARMOLENKO = ("Andriy Yarmolenko a marcat în 10 din 13 meciuri de campionat împotriva echipei Chornomorets Odesa (77%), "
              "față de 29% în restul meciurilor din baza de date. 12 goluri în total.")
MANE = ("Sadio Mané a marcat în 12 din 14 meciuri de campionat împotriva echipei Crystal Palace (86%), "
        "față de 32% în restul meciurilor din baza de date. 13 goluri în total.")
GUIMARAES = ("Newcastle United a câștigat 52% din meciurile de campionat cu Bruno Guimarães titular (76 din 145), "
             "față de 11% fără el ca titular (2 din 19), în aceeași perioadă.")
GIBBS = ("Morgan Gibbs-White are 9 goluri în ultimele 10 apariții de campionat (până la 24.05.2026). "
         "La ritmul lui de dinainte ar fi avut cam 1.5.")
LEWANDOWSKI = ("Robert Lewandowski a marcat în 15 apariții consecutive de campionat la Bayern Munich "
               "(15.02.2021 – 18.09.2021), 24 de goluri în total. În restul meciurilor din baza de date marchează în 55% din ele.")
SON = ("Heung-min Son nu a marcat niciodată împotriva echipei Wolverhampton Wanderers în 12 meciuri de campionat, "
       "deși marchează în 30% din celelalte meciuri din baza de date.")

# (name, fact, title, text, should the judge accept it)
CASES = [
    ("real-total-wrong-group", BARNES, "Barnes și Leeds", "Barnes a marcat în 6 din 8 meciuri împotriva Leeds United, adică 75%. În restul meciurilor, procentajul său este de 19%, cu 7 goluri în total.", False),
    ("real-total-wrong-group-2", YARMOLENKO, "Yarmolenko și Chornomorets", "Yarmolenko a marcat în 10 din 13 meciuri împotriva echipei Chornomorets Odesa, adică 77%. În restul meciurilor din baza de date, procentajul este de 29%, cu 12 goluri în total.", False),
    ("real-percent-of-what", MANE, "Mané și Crystal Palace", "Mané a marcat în 12 din 14 meciuri cu Crystal Palace, totalizând 13 goluri, adică 86%. În restul meciurilor din baza de date, procentajul este de 32%.", False),
    ("real-streak-unclear", LEWANDOWSKI, "Lewandowski la Bayern", "Robert Lewandowski a marcat 24 de goluri în 15 apariții consecutive de campionat, între 15.02.2021 și 18.09.2021. În rest marchează în 55% din meciuri.", False),
    ("groups-swapped", MANE, "Mané și Crystal Palace", "Mané a marcat în 32% din meciurile cu Crystal Palace. În restul meciurilor ajunge la 86%.", False),
    ("implied-cause", GUIMARAES, "Bruno schimbă Newcastle", "Bruno Guimarães o face pe Newcastle să câștige: 52% cu el titular (76 din 145), 11% fără (2 din 19).", False),
    ("estimate-as-certain", GIBBS, "Gibbs-White, în formă", "Gibbs-White are 9 goluri în ultimele 10 apariții. La ritmul de dinainte ar fi avut exact 1,5.", False),
    ("outside-context", SON, "Son și Wolves", "Son, căpitanul lui Tottenham, nu a marcat niciodată cu Wolves în 12 meciuri. În rest marchează în 30% din meciuri.", False),
    ("good-mane", MANE, "Crystal Palace, adversarul preferat al lui Mané", "Mané a marcat în 12 din 14 meciuri cu Crystal Palace, 13 goluri în total. Împotriva celorlalte echipe marchează în 32% din meciuri.", True),
    ("good-barnes", BARNES, "Leeds îi priește lui Barnes", "Barnes a marcat în 6 din 8 meciuri cu Leeds United, adică 75%, cu 7 goluri în total. În rest, ajunge la 19%.", True),
    ("good-streak", LEWANDOWSKI, "Lewandowski, 15 meciuri la rând cu gol", "Lewandowski a marcat în fiecare dintre cele 15 apariții consecutive de campionat la Bayern, 24 de goluri în total. În rest marchează în 55% din meciuri.", True),
    ("good-son", SON, "Wolves, adversarul care îi rezistă lui Son", "Son nu a marcat niciodată cu Wolverhampton în 12 meciuri de campionat. Împotriva celorlalte echipe marchează în 30% din meciuri.", True),
    ("good-guimaraes", GUIMARAES, "Newcastle, altă echipă cu Bruno titular", "Newcastle a câștigat 76 din 145 de meciuri cu Bruno Guimarães titular (52%) și doar 2 din 19 fără el titular (11%).", True),
    ("good-gibbs", GIBBS, "Gibbs-White, în formă", "Gibbs-White are 9 goluri în ultimele 10 apariții de campionat. La ritmul de dinainte ar fi avut cam 1,5.", True),
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
