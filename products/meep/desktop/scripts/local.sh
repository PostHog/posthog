#!/bin/sh
# Run Meep against your local PostHog with everything an agent needs: isolated
# data, the OAuth app, and a public address so PostHog's sandboxes can reach the
# topic tools.
#
#   sh scripts/local.sh            build and open the app
#   sh scripts/local.sh --hot      the same, with hot reloading (scripts/dev.sh)
#   sh scripts/local.sh --reset    start clean: no topics, sign in again
#
# Start local PostHog yourself first (http://localhost:8010, with Tasks, sandboxes
# and its MCP server). Data lives in $MEEP_DEV_DIR, by default .local/meep-dev.
# The public address comes from MEEP_PUBLIC_BASE_URL, or else a cloudflared quick
# tunnel this script starts (brew install cloudflared).
set -eu
cd "$(dirname "$0")/.."

hot=false
reset=false
for arg in "$@"; do
    case "$arg" in
        --hot) hot=true ;;
        --reset) reset=true ;;
        *) printf 'Unknown option %s\n' "$arg" >&2; exit 2 ;;
    esac
done

export MEEP_DEV_DIR="${MEEP_DEV_DIR:-$PWD/.local/meep-dev}"
export MEEP_POSTHOG_LOCAL=1
port="${MEEP_DEV_PORT:-47951}"
server_dir="$MEEP_DEV_DIR/server"

curl -fsS http://localhost:8010/_health >/dev/null 2>&1 || {
    printf '%s\n' 'Local PostHog is not answering at http://localhost:8010. Start it first.' >&2
    exit 1
}

# The server outlives the window, so stopping it is how a reset or a new public
# address takes effect.
stop_server() {
    pkill -f "meep-server --data-dir $server_dir" 2>/dev/null || true
    sleep 1
}

if $reset; then
    stop_server
    rm -rf "$server_dir" "$MEEP_DEV_DIR"/replica*.sqlite* "$MEEP_DEV_DIR/public-base-url"
    printf '%s\n' 'Local Meep data cleared. Sign in again with Local.'
fi
mkdir -p "$MEEP_DEV_DIR"

# Register Meep with this PostHog once.
if [ ! -s "$MEEP_DEV_DIR/posthog-local-client-id" ]; then
    sh scripts/posthog-local-app.sh
fi

# A public address for agent tools and workflow callbacks.
if [ -z "${MEEP_PUBLIC_BASE_URL:-}" ]; then
    if command -v cloudflared >/dev/null 2>&1; then
        log="$MEEP_DEV_DIR/tunnel.log"
        tunnel="cloudflared tunnel --url http://127.0.0.1:$port"
        # A tunnel started elsewhere logs its address elsewhere: replace it.
        if pgrep -f "$tunnel" >/dev/null && ! grep -q 'trycloudflare\.com' "$log" 2>/dev/null; then
            pkill -f "$tunnel" || true
            sleep 1
        fi
        if ! pgrep -f "$tunnel" >/dev/null; then
            : >"$log"
            nohup cloudflared tunnel --url "http://127.0.0.1:$port" --no-autoupdate --protocol http2 >"$log" 2>&1 &
        fi
        for _ in $(seq 1 30); do
            MEEP_PUBLIC_BASE_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$log" 2>/dev/null | tail -1 || true)
            [ -n "$MEEP_PUBLIC_BASE_URL" ] && break
            sleep 1
        done
    fi
    if [ -z "${MEEP_PUBLIC_BASE_URL:-}" ]; then
        printf '%s\n' 'No public address: agents will run without topic tools. Install cloudflared or set MEEP_PUBLIC_BASE_URL.' >&2
    fi
fi
if [ -n "${MEEP_PUBLIC_BASE_URL:-}" ]; then
    export MEEP_PUBLIC_BASE_URL
    # A running server keeps the address it started with.
    if [ "$(cat "$MEEP_DEV_DIR/public-base-url" 2>/dev/null || true)" != "$MEEP_PUBLIC_BASE_URL" ]; then
        stop_server
        printf '%s\n' "$MEEP_PUBLIC_BASE_URL" >"$MEEP_DEV_DIR/public-base-url"
    fi
    printf 'Public address: %s\n' "$MEEP_PUBLIC_BASE_URL"
fi

if $hot; then
    exec sh scripts/dev.sh --local
fi
cargo build -p meep-server -p meep --bin meep
exec target/debug/meep
