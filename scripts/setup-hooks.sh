#!/usr/bin/env bash
# Install the pre-push hook.
#
# Run once per checkout:  ./scripts/setup-hooks.sh
#
# The hook runs `make check`, which is what CI runs -- lint, the whole
# suite with the migrations check and the coverage floor, the data-quality
# rules, the public feed's guarantees and the Pages payload. One
# definition, so the hook cannot drift from CI: if the hook passes, the
# push passes.
#
# It fetches the remote's tags first. tests/test_release.py judges the
# version against the tags the checkout has, and a checkout whose tags
# are behind passes a version main has already released -- which is how
# the second unbumped version reached CI with the hook installed and
# green.
#
# `make image` is deliberately not in `check`. It builds two docker
# images and runs a container, which is minutes rather than seconds; CI
# runs it as its own job and `make image` runs it on demand.
#
# This repository had no hook at all, which is why it could sit on main
# with a version that was already tagged -- red by its own test, green in
# CI, and nothing between the two.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_DIR="$(git rev-parse --git-path hooks)"
case "$HOOK_DIR" in /*) ;; *) HOOK_DIR="$REPO_ROOT/$HOOK_DIR" ;; esac
mkdir -p "$HOOK_DIR"
HOOK="$HOOK_DIR/pre-push"

cat > "$HOOK" <<'HOOK_BODY'
#!/usr/bin/env bash
# Everything CI runs, before the push rather than after it.
# Regenerate with ./scripts/setup-hooks.sh
set -uo pipefail

# `git rev-parse` rather than a path relative to the hook: a worktree's
# hooks live in the parent's .git directory, so deriving the root from
# $0 runs the checks against the wrong tree.
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 1

mkdir -p logs/pre-push
LOG="logs/pre-push/pre-push-$(date +%Y%m%d_%H%M%S).log"

# The remote being pushed to, as git passes it. The release check reads
# the checkout's tags, and they are only as current as the last fetch.
REMOTE="${1:-origin}"
if ! git fetch -q --tags "$REMOTE"; then
  echo "⚠️  Could not fetch tags from $REMOTE; the release check runs against local tags."
fi

echo "🔍 Running everything CI runs (make check)..."
echo "   lint, tests + coverage floor, data quality, feed, pages"
echo

if make check 2>&1 | tee "$LOG"; then
  echo
  echo "✅ All checks passed. Pushing..."
  exit 0
fi

echo
echo "❌ Checks failed — push aborted."
echo "   This is what CI would have told you, minutes sooner."
echo "   Fix, or run 'make fmt' for the formatting ones."
echo "📝 Full log: $LOG"
exit 1
HOOK_BODY

chmod +x "$HOOK"
echo "✅ Installed pre-push hook at $HOOK"
echo "   It runs 'make check' — the same commands as .github/workflows/ci.yml."
