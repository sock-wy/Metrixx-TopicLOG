#!/bin/bash
# Push <out>/archive to the `archive` branch without downloading what is already there.
#   ./dashboard/archive_push.sh OUT_DIR [REPO_URL]
# Partial, sparse clone: only the branch tip's README is checked out; new files are added and pushed.
set -e
OUT="$(cd "$1" && pwd)"
URL="${2:-https://github.com/sock-wy/Metrixx-TopicLOG}"
[ -d "$OUT/archive" ] || { echo "no archive in $OUT"; exit 0; }
W="$(mktemp -d)"
git clone -q --depth 1 --filter=blob:none --no-checkout -b archive "$URL" "$W/arc"
cd "$W/arc"
git sparse-checkout init --no-cone
echo "/README.md" > .git/info/sparse-checkout
git checkout -q archive
cp -R "$OUT/archive/." .
git add --sparse -A .
if git diff --cached --quiet; then echo "archive: nothing new"; exit 0; fi
N=$(git diff --cached --name-only | wc -l | tr -d ' ')
git -c user.name="Topic Log" -c user.email="noreply@anthropic.com" commit -q -m "Archive: $(date -u +%Y-%m-%dT%H:%MZ), $N files"
for i in 1 2 3; do
  if git push -q origin archive 2>/dev/null; then echo "archive: pushed $N files"; exit 0; fi
  git pull -q --rebase origin archive || true   # another run pushed first
done
echo "archive: push failed"; exit 1
