#!/usr/bin/env bash
#
# Remove a committed .env from the ENTIRE git history and stop tracking it.
#
# WARNING: this rewrites history and requires a force-push. Anyone else with a
# clone must re-clone afterwards. Run from the repository root.
#
# PREREQUISITE (do this FIRST, it is the only thing that truly protects you):
#   1. Rotate the Groq API key in the Groq console (revoke the old one).
#   2. Rotate the Telegram bot token via @BotFather (/revoke).
# A key that has been pushed is compromised even after history is scrubbed.
#
# Requires git-filter-repo:  pip install git-filter-repo
set -euo pipefail

if ! git filter-repo --version >/dev/null 2>&1; then
  echo "git-filter-repo not found. Install it with: pip install git-filter-repo"
  exit 1
fi

echo "Stopping tracking of .env ..."
git rm --cached .env 2>/dev/null || true
grep -qxF '.env' .gitignore || echo '.env' >> .gitignore
git add .gitignore
git commit -m "chore: stop tracking .env" || true

echo "Scrubbing .env from all history ..."
git filter-repo --path .env --invert-paths --force

echo
echo "Done locally. Now re-add the remote and force-push:"
echo "  git remote add origin <your-repo-url>"
echo "  git push origin --force --all"
echo "  git push origin --force --tags"
echo
echo "Reminder: rotating the keys is what actually protects you. Do it if you haven't."
