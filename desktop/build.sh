#!/bin/bash
# Build "Topic Log.app" (macOS) from this repo: ./desktop/build.sh [ADANOS_API_KEY]
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; OUT="$ROOT/desktop/dist/Topic Log.app"
rm -rf "$OUT"; mkdir -p "$OUT/Contents/MacOS" "$OUT/Contents/Resources/app/web" "$OUT/Contents/Resources/app/"{dashboard,scoring,config}
cp "$ROOT/desktop/macos/Info.plist" "$OUT/Contents/"; cp "$ROOT/desktop/macos/TopicLog" "$OUT/Contents/MacOS/"; chmod +x "$OUT/Contents/MacOS/TopicLog"
cp "$ROOT/desktop/macos/AppIcon.icns" "$OUT/Contents/Resources/"
A="$OUT/Contents/Resources/app"
cp "$ROOT/desktop/server.py" "$A/"; cp "$ROOT/desktop/web/"* "$A/web/"
cp "$ROOT/dashboard/"{__init__.py,pipeline.py,sources.py,symbols.py,registry.py,archive.py,briefing.py,adanos_universe.json,catalysts.yaml} "$A/dashboard/"
cp "$ROOT/scoring/"{__init__.py,scoring.py} "$A/scoring/"; cp "$ROOT/config/weights_w0.yaml" "$A/config/"
curl -sL https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js -o "$A/web/d3.min.js"
python3 - "$ROOT" "$A" <<'PY'
import sys, pathlib
root, a = map(pathlib.Path, sys.argv[1:])
page = (root / "dashboard/page/index.html").read_text()
shell = (root / "desktop/web/shell.html").read_text()
(a / "web/index.html").write_text(shell.replace("{{PAGE}}", page))
PY
# optional: SEED=<dir with the latest pull> ./build.sh  -> first start shows that data
if [ -n "$SEED" ]; then mkdir -p "$A/seed"; for f in "$SEED"/*.json; do [ "$(wc -c < "$f")" -gt 2 ] && cp "$f" "$A/seed/"; done; fi
[ -n "$1" ] && printf '{"interval_min": 480, "adanos_key": "%s"}' "$1" > "$A/settings.default.json"
echo "built $OUT"
