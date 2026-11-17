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
    rm -rf "$DIR"
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

# Deletes the secrets at their expiry even if nothing runs devbox-secrets again. A later push
# writes a new expiry, so this timer then leaves the newer secrets alone.
schedule_cleanup() {
  local expires="$1"
  local wait=$((expires - $(date +%s)))
  [ "$wait" -gt 0 ] || wait=0
  local detach=()
  command -v setsid >/dev/null && detach=(setsid)
  # shellcheck disable=SC2016  # the child shell expands its own arguments
  nohup ${detach[@]+"${detach[@]}"} bash -c '
    sleep "$1"
    [ "$(cat "$2/expires" 2>/dev/null)" = "$3" ] && rm -rf "$2"
  ' _ "$wait" "$DIR" "$expires" >/dev/null 2>&1 &
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
  rm -rf "$DIR"
  mv "$staging" "$DIR"
  trap - EXIT
  schedule_cleanup "$expires"
  note_for_agents
  echo "Stored $count secret(s) in memory."
}

status() {
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
  exec "$@"
}

case "${1:-}" in
  run) shift; run "$@" ;;
  status) status ;;
  clear) rm -rf "$DIR"; echo "Cleared the lent secrets." ;;
  store) shift; store "$@" ;;
  *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
