#!/usr/bin/env bash
# PreToolUse (Bash): the git guard. Delegates to guard_bash.py, which DENIES git commit / push / add
# and destructive git (history rewrite via filter-branch/-repo, reset --hard, clean -f, git rm,
# branch -d/-D, tag -d, stash drop/clear, checkout/restore/switch discard) before they run — devant never commits,
# pushes, or rewrites git state on your behalf; you do that manually. Cooperative, not a sandbox
# (DEVANT=off disables it). Degrades to allow (exit 0) when devant/python are unavailable.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

dv_enabled || exit 0
dv_has_devant || exit 0
python3 "$LIB/guard_bash.py"
exit 0
