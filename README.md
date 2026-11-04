# Football Insights

Finds genuinely surprising patterns in football statistics, and refuses to claim anything it cannot prove.

**Live:** https://fotbal-insights.pages.dev

The hard part of an "AI insights" feed is not generating text. It is that a language model reading
stats will confidently invent numbers, and that searching thousands of combinations always turns up
patterns that are pure luck. So here the model does no calculating:

1. **Reconcile the data.** A club's game record is trusted only if player goals plus own goals equal the final score, and every listed starter has an appearance.
2. **Generate.** Deterministic SQL tests every candidate combination, not only the interesting-looking ones.
3. **Correct for the search.** Benjamini-Hochberg over all candidates tested, per generator.
4. **Verify.** Every claimed number is recounted from the raw tables by separate code. Failures are dropped.
5. **Write.** The LLM turns each verified fact into a card. Rule checks and a second LLM acting as judge compare it with the fact. A rejected card goes back with the reason; after 2 failed rewrites the card keeps the plain verified fact.

## What it finds

| Tier | Meaning | Example |
|---|---|---|
| `record` | Rare among all players | Messi scored in 21 consecutive La Liga appearances (33 goals) |
| `confirmed` | Survives the correction, unlikely to be luck | Gibbs-White: 9 goals in his last 10 league games, about 1.5 expected at his earlier rate |
| `notable` | True and striking, but could still be luck | Mané scored in 12 of 14 league games against Crystal Palace, 32% against everyone else |

The numbers in all three tiers are recounted. The tier only says how far the *pattern* can be trusted.

| Generator | Question | Compared with |
|---|---|---|
| `opponent_hot` / `opponent_cold` | Does he score unusually often, or never, against one club? | His rate against everyone else |
| `home_away` | Is his home/away split unusual? | The normal home advantage across all players |
| `scoring_streak` | Longest run of league appearances with a goal | His career rate, and all other players |
| `super_sub` | Better off the bench? | His starter rate times the general bench boost (about 2x) |
| `recent_form` | Last 10 league games | His own earlier rate |
| `team_head_to_head` | Does a club dominate one opponent? | Its win rate against everyone else |
| `with_without` | Does a club win more when he starts? | Games without him, between his first and last start of each season |

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m insights.build_db   # downloads about 230 MB of CSVs, builds data/football.duckdb
.venv/bin/python -m insights.run        # writes data/insights.json
.venv/bin/python -m pytest

# Model-written cards: put GEMINI_API_KEY=... in .env (a free Google AI Studio key works)
.venv/bin/python -m insights.write_feed # writes data/feed.json
.venv/bin/python -m evals.judge_eval    # measures the judge on labeled cards

# The feed page, at http://localhost:8765
.venv/bin/python -m insights.build_site # recounts everything, writes site/feed.json
python3 -m http.server 8765 --directory site
```

Pushing a change to `site/` publishes it to Cloudflare Pages through GitHub Actions (`.github/workflows/deploy.yml`).

All model calls go through `insights/llm.py`, so changing provider means changing that one file. Answers are cached on disk. Currently only Gemini is implemented.

The page is static. Since the data is frozen, a server recounting on every request would always return the same result, so the recount happens at build time and the build stops if any number fails. Each card's "See the proof" button lists the matches behind the claim. The big numbers and comparison bars come from the verified numbers, not from the model's text, so only the sentences are model-written.

## How it is checked

- **Against facts known independently:** the generator rediscovers Messi's 21-game run, Vardy's 11 and Quagliarella's 11 with no hints, and Messi's 2012/13 league season matches the official 32 games and 46 goals.
- **Against tampering:** tests confirm the verifier rejects an altered count and a game the player did not play.
- **Against false streaks:** a run must not span a game whose data could not be reconciled.

### Checking the model's text

Rule checks catch invented numbers, swapped "X of Y" pairs, numbers written as words, superlatives, causal words and gendered pronouns. They cannot catch correct numbers attached to the wrong thing, which the writer really did: "in the other games the rate is 19%, with 7 goals in total", where the 7 goals were against one opponent. That is why there is a judge.

| Judge version | Wrong cards caught | Good cards accepted |
|---|---|---|
| Romanian, one overall verdict | 5 of 8 | 6 of 6 |
| Romanian, one answer per kind of error | 8 of 8 | 4 of 6 |
| English, one answer per kind of error (current) | 8 of 8 | 6 of 6 |

The English test set is a translation with adjusted good cards, so the last row is not a like-for-like improvement.

On the final run of 49 cards, all ended up model-written, 42 on the first try and 7 after a rewrite. Claude read all 49 against their facts and found no wrong or misattached number; no person has reviewed them. In the earlier Romanian run, that same read-through caught a misattached comparison the judge had passed. The fix was to make the source fact less ambiguous.

## Known limits

- **The data is frozen.** The source [dcaribou/transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets) (CC0) stopped updating in July 2026. Feeds are "as of May 2026", not live.
- **Player insights cover 14 European leagues, league games only.** Cups and European competitions are incomplete in the source (most under 75% of matches reconcile), so "career rate" means league games in the database, not a full career.
- **No Romanian Superliga insights.** The source has no player appearances for it and only two partial seasons of results, too few meetings for head-to-head (minimum 8).
- **The verifier checks against the source, not against reality.** If Transfermarkt is wrong, so is the feed.
- **Patterns are associations, not causes.** `with_without` especially: rotation and injuries also depend on the opponent.
- **The significance tests are simplified.** They treat games as independent and a player's rate as constant, which ignores role changes and opponent strength.
- **Thresholds are judgment calls.** The false discovery rate, minimum samples and scoring weights are in `insights/config.py` and the generators, and were set while looking at this same data.
- **The judge is an LLM too, and its numbers are not a real accuracy rate.** The 14 labeled cards were written during development and the judge was adjusted after seeing them, so they show it can catch these errors, not how often it will.
- **The writing is correct but repetitive.** The project uses the cheapest available model (`gemini-3.1-flash-lite`).
- **Club names in the plain facts come straight from the source,** so some are formal or in Cyrillic. The model shortens them on the cards, unchecked.
