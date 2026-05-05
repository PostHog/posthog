#!/bin/bash
set -euo pipefail
# Wrapper that proxies `gh` invocations to the agent-server's POST /gh
# endpoint so they execute with the agent-server's freshly-rotated
# GH_TOKEN/GITHUB_TOKEN env. Running `gh` directly here would only see
# whatever token was baked into this child process at spawn time — which
# is exactly what `posthog/set_token` rotates away from for long-lived
# sandboxes (see PostHog/code#2018).
#
# Loopback-only and JWT-free by design: the /gh route enforces a remote
# loopback address, so the wrapper has nothing to forward.
#
# Limitation: stdin (e.g. `gh api ... --input -`) is not forwarded — the
# /gh contract only accepts {args, cwd, timeoutMs}. Use `--input <file>`
# instead, or call `gh-bin` directly when stdin is required.

AGENT_HOST="${POSTHOG_AGENT_SERVER_HOST:-127.0.0.1}"
AGENT_PORT="${POSTHOG_AGENT_SERVER_PORT:-8080}"

# Encode argv into a JSON body. `jq -n --args` handles arbitrary argv
# (quotes, newlines, multibyte) without shell-quoting hazards.
body=$(jq -n --arg cwd "$PWD" --args '{cwd: $cwd, args: $ARGS.positional}' -- "$@")

# nosemgrep: trailofbits.generic.curl-unencrypted-url.curl-unencrypted-url
# HTTP (not HTTPS) is correct here: the /gh endpoint is loopback-only by
# agent-server design, so traffic never leaves the sandbox. TLS would add
# certificate plumbing for a 127.0.0.1 socket with no security benefit.
response=$(curl -sS --fail-with-body \
  -X POST \
  -H "Content-Type: application/json" \
  --max-time 120 \
  "http://${AGENT_HOST}:${AGENT_PORT}/gh" \
  --data-binary "$body") || {
  printf 'gh wrapper: agent-server /gh request failed\n' >&2
  [ -n "${response:-}" ] && printf '%s\n' "$response" >&2
  exit 1
}

stdout=$(jq -r '.stdout // ""' <<<"$response")
stderr=$(jq -r '.stderr // ""' <<<"$response")
# Coerce null exitCode (process killed by signal or /gh timeout) to a
# non-zero status so callers don't treat it as success.
exit_code=$(jq -r '.exitCode // 1' <<<"$response")
timed_out=$(jq -r '.timedOut // false' <<<"$response")

[ -n "$stdout" ] && printf '%s' "$stdout"
[ -n "$stderr" ] && printf '%s' "$stderr" >&2

if [ "$timed_out" = "true" ]; then
  printf 'gh wrapper: command timed out\n' >&2
fi

exit "$exit_code"
