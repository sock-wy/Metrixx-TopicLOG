# desktop

**Status:** v0.1 — macOS app

`Topic Log.app`: the dashboard as a standalone desktop app. A local Python server pulls every source on a timer (15 min to 24 h, default 8 h, set in the app bar), keeps the history in `~/Library/Application Support/TopicLog/data/`, and shows the same page as the claude.ai dashboard (`dashboard/page/index.html`) through a small stand-in for the dashboard runtime (`web/shim.js`).

- First launch finds Python 3.9+ (Anaconda, Homebrew or system), creates a private venv with `pyyaml` and `pywebview`, then opens a native window. Without pywebview it opens a Chrome app window, else the default browser.
- The Adanos key can be set from the app bar; it is stored in `settings.json` in the support folder (mode 600), never in the repo.
- Filters and algorithm settings are kept per machine in the window's local storage.
- Its history is separate from the cloud dashboard's.

Build: `./desktop/build.sh [ADANOS_API_KEY]` → `desktop/dist/Topic Log.app`.


## Windows

`TopicLog.exe` is built by GitHub Actions (`.github/workflows/windows-app.yml` runs `desktop/windows/build_win.py`, PyInstaller one-file, then `TopicLog.exe --selftest out.json`, which runs a real pull without an Adanos key). Data lives in `%APPDATA%\TopicLog\`. The .exe carries no key (the repo is public); put `settings.default.json` (`{"interval_min": 480, "adanos_key": "..."}`) next to the .exe, or use the Adanos key button.
