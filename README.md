# claude-skills

Skills for [Claude Code](https://claude.com/claude-code) that I built for marketing and growth work. Each folder under `skills/` is a self-contained skill: a `SKILL.md` that tells Claude when and how to use it, plus any scripts and tests it needs.

## The skills

### [`schema-markup`](skills/schema-markup/)

Audits a page's schema.org structured data (JSON-LD) against Google's rich-result requirements, then generates ready-to-paste JSON-LD for whatever is missing or broken.

- **Why I built it:** checking structured data by hand meant reading Google's docs type by type, and a general SEO review usually stops at "schema present: yes/no". This skill answers which required and recommended properties are missing and hands back the fix.
- **What it needs:** nothing beyond Claude Code. Works on any public URL or pasted HTML.
- **Status:** complete.

### [`ad-fatigue-detection`](skills/ad-fatigue-detection/)

Scores Meta (Facebook/Instagram) ads for creative fatigue from daily per-ad trends, explains why an ad is fatiguing, and recommends the next action. Read-only: it never edits or pauses ads.

- **Why I built it:** Ads Manager shows totals for a date range, which hides decay. A creative can look fine on average while its CTR has been sliding for two weeks. This skill reads the day-by-day trend for every ad and flags the ones wearing out, with guardrails so small-spend or badly tracked ads are reported as "directional" rather than as a firm call.
- **What it needs:** a **Meta ad account** and a **Meta Marketing API access token** with `ads_read` (set `META_AD_ACCOUNT_ID` and `META_ACCESS_TOKEN` in `.env`), plus Python 3. Without them it stops with a message saying which values are missing. The test suite (98 tests) runs without any account.
- **Status:** `score` (live fatigue scoring) and `backtest` (no-lookahead validation and threshold calibration) are complete. `diagnose`, `report` and `run-weekly` are planned and show as "not yet" in `--help`.

## Install

Clone the repo and symlink the skills you want into your Claude Code skills folder:

```bash
git clone https://github.com/gop-v-5/claude-skills.git
cd claude-skills
ln -s "$PWD/skills/schema-markup" ~/.claude/skills/schema-markup
```

Each skill's own `SKILL.md` / `README.md` covers its setup (for example copying `.env.example` to `.env`).

## Tests

```bash
cd skills/ad-fatigue-detection && pip3 install -r requirements.txt && python3 -m pytest -q
```

## Licence

[MIT](LICENSE)
