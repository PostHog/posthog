#!/usr/bin/env bash
# Create posthog-code-codex-own-subscription-cloud, or widen it to everyone.
#
# The flag gates cloud Codex tasks that bill the user's own ChatGPT plan. Run
# this only after the OpenAI terms questions in the pull request are answered:
# at 100% every Desktop user can spend their plan on a cloud run.
#
#   POSTHOG_PERSONAL_API_KEY=phx_... ./rollout-codex-cloud-subscription-flag.sh
#
# The key needs the feature_flag:read and feature_flag:write scopes, and access
# to the project. Create one at Settings > Personal API keys.
set -euo pipefail

FLAG_KEY="posthog-code-codex-own-subscription-cloud"
FLAG_NAME="PostHog Code: run cloud Codex tasks on your own ChatGPT plan"
HOST="${POSTHOG_HOST:-https://us.posthog.com}"
PROJECT_ID="${POSTHOG_PROJECT_ID:-2}"

ASSUME_YES=false
[ "${1:-}" = "--yes" ] && ASSUME_YES=true

for binary in curl jq; do
  if ! command -v "$binary" >/dev/null 2>&1; then
    echo "This script needs $binary. Install it and try again." >&2
    exit 1
  fi
done

if [ -z "${POSTHOG_PERSONAL_API_KEY:-}" ]; then
  echo "Set POSTHOG_PERSONAL_API_KEY to a key with feature_flag:write." >&2
  exit 1
fi

HOST="${HOST%/}"
FLAGS_URL="$HOST/api/projects/$PROJECT_ID/feature_flags"

# Fails the script on a non-2xx rather than passing an error body to jq.
api() {
  local method="$1" url="$2" data="${3:-}"
  local response status body
  local -a args=(
    --silent --show-error --write-out '\n%{http_code}'
    --request "$method" "$url"
    --header "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY"
  )
  if [ -n "$data" ]; then
    args+=(--header "Content-Type: application/json" --data "$data")
  fi
  if ! response=$(curl "${args[@]}"); then
    echo "Could not reach $url." >&2
    exit 1
  fi
  status=$(printf '%s' "$response" | tail -n 1)
  body=$(printf '%s' "$response" | sed '$d')
  if [ "${status#2}" = "$status" ]; then
    echo "$method $url returned $status:" >&2
    printf '%s\n' "$body" >&2
    exit 1
  fi
  printf '%s' "$body"
}

# An empty properties list with a 100% rollout is "everyone".
read -r -d '' EVERYONE_FILTERS <<'JSON' || true
{"groups": [{"properties": [], "rollout_percentage": 100}]}
JSON

existing=$(api GET "$FLAGS_URL/?key=$FLAG_KEY&limit=1")
flag_id=$(printf '%s' "$existing" | jq -r '.results[0].id // empty')

if [ -n "$flag_id" ]; then
  printf '%s' "$existing" | jq -r '
    .results[0]
    | "Flag \(.key) exists (id \(.id)), active=\(.active), archived=\(.archived).",
      "Current release conditions:",
      (.filters.groups | tojson)'
  action="widen it to everyone at 100%"
else
  echo "Flag $FLAG_KEY does not exist in project $PROJECT_ID."
  action="create it, enabled for everyone at 100%"
fi

if [ "$ASSUME_YES" != true ]; then
  printf 'This will %s on %s. Continue? [y/N] ' "$action" "$HOST"
  read -r reply
  case "$reply" in
    y | Y | yes | YES) ;;
    *)
      echo "Stopped. Nothing changed."
      exit 0
      ;;
  esac
fi

if [ -n "$flag_id" ]; then
  # `filters` replaces the whole object, so the narrower conditions go away.
  payload=$(jq -n --argjson filters "$EVERYONE_FILTERS" \
    '{active: true, archived: false, deleted: false, filters: $filters}')
  result=$(api PATCH "$FLAGS_URL/$flag_id/" "$payload")
else
  payload=$(jq -n --arg key "$FLAG_KEY" --arg name "$FLAG_NAME" \
    --argjson filters "$EVERYONE_FILTERS" \
    '{key: $key, name: $name, active: true, filters: $filters}')
  result=$(api POST "$FLAGS_URL/" "$payload")
fi

printf '%s' "$result" | jq -r '
  "Done. \(.key) is active=\(.active) for \(.filters.groups[0].rollout_percentage)% of everyone.",
  "\($ENV.POSTHOG_HOST // "https://us.posthog.com" | sub("/$"; ""))/project/\($ENV.POSTHOG_PROJECT_ID // "2")/feature_flags/\(.id)"'
