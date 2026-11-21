#!/usr/bin/env bash
# Publish the friend-invite landing page to the gh-pages branch, which GitHub Pages serves.
#
# Only two files are ever on that branch (invite-done.html and .nojekyll), so nothing else from
# the repository is served, and pushes to main cannot change what friends see. Anything pushed to
# gh-pages goes live within a minute or two, so run this only when the page itself changed.
#
# Usage: bash dev/publish_landing_page.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python dev/build_landing_page.py

TMP="$(mktemp -d)"
cleanup() {
  git -C "$ROOT" worktree remove --force "$TMP/site" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

if git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
  git fetch -q origin gh-pages
  git worktree add -q -B gh-pages "$TMP/site" origin/gh-pages
else
  git worktree add -q --orphan -b gh-pages "$TMP/site"
fi

cd "$TMP/site"
git rm -rq --ignore-unmatch . >/dev/null 2>&1 || true   # start empty: only what is copied below stays
cp "$ROOT/docs/invite-done.html" invite-done.html
: > .nojekyll
git add -A

if git diff --cached --quiet; then
  echo "gh-pages is already up to date"
else
  git commit -q -m "Publish the friend invite landing page"
  git push -q origin gh-pages
  echo "published: https://kanemari.github.io/kakao_talk_notifier/invite-done.html"
fi
