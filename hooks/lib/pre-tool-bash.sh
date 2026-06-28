#!/usr/bin/env bash
# PreToolUse (Bash): the action-guard. The edit guard only sees Write|Edit, so git/deploy/rm/
# exfil run through Bash unguarded. This ASKS for confirmation before outward (commit/push/
# publish/deploy), irreversible/destructive (rm -rf, git rm, reset --hard, clean -f, find -delete,
# DROP/TRUNCATE, /dev/tcp), uninspectable code (bash -c, python -c, curl|sh, eval), exfil
# (curl/wget upload, header/url with $var, scp/rsync/nc), credential-shaped literals, and writes to
# devant's own store (.devant/). It's a cooperative guard, not a sandbox: a hook can't see the
# prompt to know you asked, so it asks (you approve if you meant it); read-only commands pass.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
CMD="$(printf '%s' "$INPUT" | json_field tool_input.command)"
[ -z "$CMD" ] && exit 0

RISK=""
add() { RISK="${RISK:+$RISK; }$1"; }
g() { printf '%s' "$CMD" | grep -qE "$1"; }   # match a pattern in the command
# Command-start anchor: a verb at the start, after ; | && or a subshell '(' (so it doesn't match
# inside echo "…"), seeing through leading env-assignments (GIT_DIR=x git …) and common wrappers
# (sudo/nice/time/env/command/xargs/nohup …) so `sudo rm -rf` / `find . | xargs rm -rf` are caught.
_DV_ENV='[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+'
_DV_WRAP='(sudo|doas|nice|time|env|command|xargs|nohup|stdbuf|setsid|ionice)([[:space:]]+(-{1,2}[A-Za-z0-9][^[:space:]]*|[0-9]+))*[[:space:]]+'
CS="(^|[;&|(]|&&)[[:space:]]*(${_DV_ENV}|${_DV_WRAP})*"

# Outward: commit/push regardless of intervening options (e.g. `git -c gpgsign=false commit`).
g "${CS}git\b[^|;&]*\b(commit|push)\b" && add "git commit/push"
g "${CS}(npm|yarn|pnpm)[[:space:]]+publish\b|${CS}docker[[:space:]]+push\b|${CS}gh[[:space:]]+(release|pr[[:space:]]+create)\b|${CS}(kubectl[[:space:]]+(apply|delete)|helm[[:space:]]+(install|upgrade|delete)|terraform[[:space:]]+(apply|destroy))\b" && add "publish/deploy"
# Recursive/forced delete (short and GNU long flags), incl. git rm.
g "${CS}rm[[:space:]]+(-[a-zA-Z]*[rR]|--recursive)|${CS}git[[:space:]]+rm\b" && add "recursive delete"
# Non-rm destruction.
g "${CS}find\b[^|;&]*-(delete|exec[[:space:]]+rm)\b|${CS}dd\b[^|;&]*[[:space:]]of=|${CS}shred\b|${CS}truncate\b[^|;&]*-s[[:space:]]*0|${CS}chmod[[:space:]]+-R\b" && add "destructive file op"
# Discard committed/uncommitted work; git tag only when it deletes/force-moves (not `git tag -l`).
g "${CS}git[[:space:]]+(reset[[:space:]]+--hard|clean[[:space:]]+-[a-zA-Z]*f|checkout[[:space:]]+--|filter-branch|branch[[:space:]]+-D|stash[[:space:]]+(clear|drop)|tag[[:space:]]+-(d|f))" && add "discards work"
# Inline code execution — only flag when the payload itself looks risky (don't nag `python -c 'print(2+2)'`).
if printf '%s' "$CMD" | grep -qE "${CS}(sh|bash|zsh|dash|ksh)[[:space:]]+(-[A-Za-z]*c|-lc)\b|${CS}(python[0-9.]*|perl|ruby|node|php|deno)[[:space:]]+(-c|-e)\b" \
   && printf '%s' "$CMD" | grep -qE '\brm[[:space:]]|curl|wget|os\.system|subprocess|socket|urllib|requests\.|base64|/etc/|/dev/|exec\(|eval\(|open\(|shutil|popen'; then add "runs risky inline code"; fi
# Pipe network output into an interpreter, or pipe into a bare/stdin interpreter (curl|sh, |bash, |python -).
g "(curl|wget|fetch)\b[^|;&]*\|[[:space:]]*(sudo[[:space:]]+)?(sh|bash|zsh|python[0-9.]*|perl|ruby|node)\b|\|[[:space:]]*(sh|bash|zsh|dash|ksh)([[:space:]]|\$)|\|[[:space:]]*(python[0-9.]*|perl|ruby|node|php)[[:space:]]+-([[:space:]]|\$)" && add "pipe-to-shell"
# eval/fetch-then-exec of fetched content (eval "$(curl …)" ; curl -o x && bash x).
g "eval[^|;&]*\\\$\([^)]*(curl|wget|fetch)|(curl|wget)\b[^|]*-[oO]\b[^|]*(;|&&)[^|]*(sh|bash|zsh|python[0-9.]*|perl|ruby|node)\b" && add "fetch-then-execute"
# Network exfil: data-upload flags, url with $(...)/backtick, /dev/tcp, nc, scp/rsync to a host.
g "(curl|wget)\b[^|;&]*(--data|--data-binary|--data-urlencode|--post-data|--post-file|--upload-file|-d[[:space:]@]|-T[[:space:]]|-F[[:space:]])" && add "network/exfil"
g "(curl|wget)\b[^|;&]*(\\\$\(|\`)" && add "network/exfil"
g ">[[:space:]]*/dev/(tcp|udp)/|${CS}sftp\b" && add "network/exfil"
g "${CS}nc\b[[:space:]]|${CS}(scp|rsync)\b[^|;&]*[^[:space:]/]:[^[:space:]]" && add "network/exfil"
# Persistence (shell rc / cron).
g ">>?[[:space:]]*[^|;&]*\.(bashrc|zshrc|bash_profile|profile|zprofile)\b|${CS}crontab\b" && add "persistence (shell rc/cron)"
# Destructive SQL / truncating a risky file (db/secret).
printf '%s' "$CMD" | grep -qiE '\b(drop[[:space:]]+(table|database)|truncate[[:space:]]+table)\b' && add "destructive SQL"
g ">[[:space:]]*[^[:space:]|;&]*\.(db|sql|sqlite3?|key|pem|env)\b" && add "truncates a db/secret file"
# A credential-shaped literal written via Bash (echo/printf/heredoc > file) bypasses the edit guard.
# Left boundary so 'sk-' doesn't fire inside 'task-…'.
printf '%s' "$CMD" | grep -qE '(-----BEGIN [A-Z ]*PRIVATE KEY-----|([^A-Za-z0-9]|^)AKIA[0-9A-Z]{16}|([^A-Za-z0-9_-]|^)(ghp_|gho_|github_pat_|xox[baprs]-|sk-ant-|sk_live_|sk-|glpat-)[A-Za-z0-9_-]{16,})' && add "credential-shaped literal in command"
# Self-disarm: weakening a devant rule from Bash should be visible to the user.
g "bin/devant[^|;&]*((decide[^|;&]*--supersedes)|--exempt|(add-node[^|;&]*--severity[[:space:]]+warn))" && add "weakens a devant rule (review the change)"
# Integrity: writing/deleting devant's own store (rm/mv/sqlite3/redirect, cd into it, or git add) disarms its rules.
g "(\brm\b|\bmv\b|\bcp\b|\btee\b|\bdd\b|\bsqlite3\b|\bsed\b[^|;&]*-i|>>?)[^|;&]*(\.devant/|\bintent\.db\b|\busage\.log\b)|\bcd[[:space:]]+[^|;&]*\.devant|git[[:space:]]+add[^|;&]*(\.devant|\.codegraph)" && add "writes to .devant (would alter devant's own rules/state)"

[ -z "$RISK" ] && exit 0

REASON="[devant] This command is outward or irreversible ($RISK). Confirm you intended it this turn — devant never commits, pushes, publishes, deploys, or destroys without your explicit go-ahead."
python3 -c 'import sys,json;print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":sys.argv[1]}}))' "$REASON"
exit 0
