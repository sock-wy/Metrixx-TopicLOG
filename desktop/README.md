# desktop

**Status:** v0.1 — macOS app

`Topic Log.app`: the dashboard as a standalone desktop app. A local Python server pulls every source at the times set with Schedule… in the app bar (Chicago time; default 06:00 and 15:15 CT; a pull missed while the Mac slept runs on wake), keeps the history in `~/Library/Application Support/TopicLog/data/`, and shows the same page as the claude.ai dashboard (`dashboard/page/index.html`) through a small stand-in for the dashboard runtime (`web/shim.js`).

- First launch finds Python 3.9+ (Anaconda, Homebrew or system), creates a private venv with `pyyaml` and `pywebview`, then opens a native window. Without pywebview it opens a Chrome app window, else the default browser.
- The Adanos key can be set from the app bar; it is stored in `settings.json` in the support folder (mode 600), never in the repo.
- Filters and algorithm settings are kept per machine in the window's local storage.
- Its history is separate from the cloud dashboard's.

Build: `./desktop/build.sh [ADANOS_API_KEY]` → `desktop/dist/Topic Log.app`.


## Windows

`TopicLog.exe` is built by GitHub Actions (`.github/workflows/windows-app.yml` runs `desktop/windows/build_win.py`, PyInstaller one-file, then `TopicLog.exe --selftest out.json`, which runs a real pull without an Adanos key and reports every data source; a source that cannot be reached shows as a warning). Data lives in `%APPDATA%\TopicLog\`. The .exe carries no key (the repo is public); put `settings.default.json` (`{"adanos_key": "..."}`) next to the .exe, or use the Adanos key button.

## v0.9 (Nov 3)
- Pulls at 07:00 and 16:15 ET by default (older saved intervals move to this once).
- MYCAST episodes (v0.8: digest → Claude draft → review → ElevenLabs MP3) now always write with `claude-sonnet-5-5`, also when an older `keys.json` names another model.
- Daily Topic Log `topic_log_YYYY-MM-DD.json` in the data folder's `daily/`, copied to `~/Desktop/TopicLog/daily/` when that folder exists (macOS may ask once for Desktop access).
- Nasdaq and Yahoo requests send browser headers (home networks hung or got 401/429 without them); source errors carry a short hint (antivirus/HTTPS inspection, firewall, rate limit).

## v1.0 (Nov 8)
- **Schedule** (app bar): pull times of day in Chicago time, 24-hour, up to 6, at least 30 min apart, each with an on switch; "Weekdays only" optional. 15:15 CT (= 16:15 ET) is the pick of record and cannot be removed. Apply never starts a pull: the schedule starts from the next time. Stored in settings.json as `schedule`.
- **Topic Log Data** on the Desktop (`~/Desktop/Topic Log Data/`, Windows: Desktop or OneDrive\Desktop): `daily/` (day files), `rank_history/` (one full ranking per pull, `rank_YYYY-MM-DD_HHMMCT.json`), `digests/` (each pull's claude_digest + "Export JSON for Claude"), `audio/` (episode MP3s, no longer Downloads), `scripts/` (episode .md/.txt exports), `exports/` (PDF / Excel). Every start copies what is already on the computer (never moves or deletes). **Data folder** button opens it.
- **Rank changes** tab (`dashboard/rankhist.py`): latest pull vs the pull before, pick of record vs the day before (entered / left the top 10, biggest moves), rank path of today's top 10, top-10 turnover per pull, streaks in the top 10, most unstable ranks, daily picks and their next-day rank. History is permanent (`rank_history.json`, top 50 per pull), backfilled from the archive (`dashboard/backfill/rank_seed.json`, Oct 23 on) and the local 10-day score history.
- **Export PDF / Excel** (Rank changes tab, `dashboard/report.py`): ranking overall and by category (stocks, crypto, macro, themes, commodities, indexes, rates, FX, private), plus every rank-change table. Needs openpyxl and reportlab (installed on first start of v1.0, needs internet once).
- **Episode → Use my own script**: paste a finished script (e.g. Jim's), approve, Make audio with ElevenLabs. No Claude draft, no Anthropic key needed.
- Pick of record = first pull at or after 16:10 ET (15:10 CT); the Episode tab no longer calls the 16:15 ET pull "not the pick of record".
- Windows: CI also publishes TopicLog.exe to the `windows-latest` release.

## v1.1 (Nov 8)
- **Four sections** at the top: Workbench · Market (Briefing, Raw data, Market data, Topics & events) · Changes (Rank changes, Daily picks, Daily steps) · Apps (Episode). Each section shows its own tabs.
- **Rank changes, reworked** around why the ranking moved, comparing today with the day before (pick of record) or the latest pull with the one before:
  - Biggest rank moves and what drove them: for each big mover, the change in each angle's contribution to the score (attention 70%, price & volume 25%, money 5%; each input as its percentile on that pull).
  - Four angles, risers and fallers: Attention (mentions vs 20-day normal), Money (prediction-market open interest vs normal), Price & volume (24h move in sigma), Sentiment (average Adanos sentiment).
  - Daily picks and their next-day rank. The rank-path, turnover and volatility views were removed.
  - The rank history now keeps each topic's inputs per pull (`in`, `c` fields); the seed was rebuilt from the archive with them.
- **Episode: two prompts.** `episode_prompt.md` = Market angle (trader's read); `episode_prompt_teaching.md` = Teaching moment (the story as a worked example of one concept). Pick the angle next to Draft script; "Rewrite as …" switches an episode to the other angle. A copy of either file in the support folder overrides the bundled one.
- Exports: drivers and four-angle tables added; volatility and turnover removed.
