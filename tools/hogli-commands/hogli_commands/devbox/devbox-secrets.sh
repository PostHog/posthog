#!/usr/bin/env bash
# Holds secrets that `hogli devbox:secrets:push` lent to this devbox, and hands them to one
# command at a time. They live in memory (/dev/shm), only this user can read them, and they
# stop working when the lend expires or the box stops.
#
#   devbox-secrets run -- <command>   run a command with the lent secrets as env vars
#   devbox-secrets status             names and time left, never values
#   devbox-secrets clear              forget them now
#   devbox-secrets store <expires>    used by hogli: NAME=value lines on stdin, expiry in epoch seconds

set -euo pipefail

DIR="${DEVBOX_SECRETS_DIR:-/dev/shm/devbox-secrets-$(id -u)}"
ENV_FILE="$DIR/env"
EXPIRES_FILE="$DIR/expires"
# store, clear and both expiry paths hold this lock, so an old expiry can't delete a newer lend.
LOCK_FILE="$DIR.lock"
# flock is in util-linux on every box. Without it (macOS), the steps run unlocked.
lock() {
  if command -v flock >/dev/null; then flock 9; fi
}
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
MD_BEGIN="<!-- BEGIN devbox-secrets (managed by hogli devbox:secrets:push) -->"
MD_END="<!-- END devbox-secrets -->"

die() {
  echo "devbox-secrets: $*" >&2
  exit 1
}

# Removes the secrets once their time is up. Prints nothing when there are none.
expired() {
  [ -f "$EXPIRES_FILE" ] || return 0
  if [ "$(date +%s)" -ge "$(cat "$EXPIRES_FILE")" ]; then
    (lock && rm -rf "$DIR") 9>"$LOCK_FILE"
    return 0
  fi
  return 1
}

note_for_agents() {
  mkdir -p "$(dirname "$CLAUDE_MD")"
  touch "$CLAUDE_MD"
  local rest
  rest=$(awk -v b="$MD_BEGIN" -v e="$MD_END" '$0 == b { skip = 1; next } $0 == e { skip = 0; next } !skip' "$CLAUDE_MD")
  {
    echo "$MD_BEGIN"
    echo "API keys lent from the owner's laptop (for example OPENAI_API_KEY, ANTHROPIC_API_KEY) are not in the environment."
    echo "Run a command that needs them with \`devbox-secrets run -- <command>\`. \`devbox-secrets status\` lists the names and the time left."
    echo "Never print, log or write the values to files."
    echo "$MD_END"
    if [ -n "$rest" ]; then
      echo
      printf '%s\n' "$rest"
    fi
  } > "$CLAUDE_MD.tmp"
  mv "$CLAUDE_MD.tmp" "$CLAUDE_MD"
}

# Deletes the secrets at their expiry. A later push writes a new expiry, so an older timer then
# leaves the newer secrets alone.
expire_at() {
  local expires="$1"
  local wait=$((expires - $(date +%s)))
  [ "$wait" -le 0 ] || sleep "$wait"
  (
    lock
    if [ "$(cat "$EXPIRES_FILE" 2>/dev/null)" = "$expires" ]; then
      rm -rf "$DIR"
    fi
  ) 9>"$LOCK_FILE"
}

# Runs expire_at in the background, so the secrets go even if nothing runs devbox-secrets again.
schedule_cleanup() {
  local detach=()
  command -v setsid >/dev/null && detach=(setsid)
  nohup ${detach[@]+"${detach[@]}"} bash "$0" expire-at "$1" >/dev/null 2>&1 &
}

store() {
  local expires="${1:-}"
  [[ "$expires" =~ ^[0-9]+$ ]] || die "store needs the expiry in epoch seconds"
  umask 077
  mkdir -p "$(dirname "$DIR")"
  # Build the new set aside and swap it in whole, so a failed push leaves neither half a set
  # nor a set without an expiry, and keeps the previous one.
  local staging
  staging=$(mktemp -d "$(dirname "$DIR")/.devbox-secrets-staging.XXXXXX")
  trap 'rm -rf "$staging"' EXIT
  local line name value count=0
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    name="${line%%=*}"
    value="${line#*=}"
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "found a line without a valid NAME=; kept the previous secrets"
    printf 'export %s=%q\n' "$name" "$value" >> "$staging/env"
    count=$((count + 1))
  done
  [ "$count" -gt 0 ] || die "nothing to store"
  echo "$expires" > "$staging/expires"
  (
    lock
    rm -rf "$DIR"
    mv "$staging" "$DIR"
  ) 9>"$LOCK_FILE"
  trap - EXIT
  schedule_cleanup "$expires"
  note_for_agents
  echo "Stored $count secret(s) in memory."
}

# Processes started by `run` keep the secrets in their environment after the files go.
holders() {
  { grep -lxz "DEVBOX_SECRETS_LENT=1" /proc/[0-9]*/environ 2>/dev/null || true; } | wc -l | tr -d ' '
}

status() {
  local running
  running=$(holders)
  if [ "$running" -gt 0 ]; then
    echo "Still running with lent secrets: $running process(es). Stop them, or restart the box."
  fi
  if expired || [ ! -f "$ENV_FILE" ]; then
    echo "No secrets lent to this box."
    return 0
  fi
  local left=$(( $(cat "$EXPIRES_FILE") - $(date +%s) ))
  echo "Lent: $(sed -E 's/^export ([^=]+)=.*/\1/' "$ENV_FILE" | paste -sd ' ' -)"
  echo "Time left: $((left / 3600))h $(((left % 3600) / 60))m"
}

run() {
  [ "${1:-}" = "--" ] && shift
  [ $# -gt 0 ] || die "usage: devbox-secrets run -- <command>"
  if expired || [ ! -f "$ENV_FILE" ]; then
    die "no secrets lent to this box, or they expired. Ask the owner to run: hogli devbox:secrets:push"
  fi
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  export DEVBOX_SECRETS_LENT=1
  exec "$@"
}

case "${1:-}" in
  run) shift; run "$@" ;;
  status) status ;;
  clear)
    (lock && rm -rf "$DIR") 9>"$LOCK_FILE"
    echo "Cleared the lent secrets."
    ;;
  store) shift; store "$@" ;;
  expire-at) shift; expire_at "$@" ;;
  *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
