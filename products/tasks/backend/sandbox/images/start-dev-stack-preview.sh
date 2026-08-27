#!/usr/bin/env bash
set -Eeuo pipefail

STATE_DIR=/tmp/posthog-preview
STATUS_FILE="$STATE_DIR/status.json"
LOCK_FILE="$STATE_DIR/lock"
CADDYFILE="$STATE_DIR/Caddyfile"
PROXY_CONTAINER=posthog-preview-proxy
WEB_HEALTH_URL=http://localhost:8010/_health
VITE_HEALTH_URL=http://127.0.0.1:8234/@vite/client
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-360}"

mkdir -p "$STATE_DIR"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

write_status() {
	state="$1"
	error="$(printf '%s' "${2:-}" | tr -d '"\\' | tr '\n\r\t' '   ' | cut -c1-500)"
	{
		printf '{"state":"%s","started_at":"%s","updated_at":"%s"' "$state" "$STARTED_AT" "$(now)"
		if [ -n "$error" ]; then
			printf ',"error":"%s"' "$error"
		fi
		printf '}\n'
	} >"$STATUS_FILE.tmp" && mv "$STATUS_FILE.tmp" "$STATUS_FILE"
}

fail() {
	trap - ERR
	echo "preview_failed: $1" >&2
	write_status failed "$1"
	exit 1
}

on_unexpected_exit() {
	trap - ERR
	echo "preview_failed: unexpected exit at line $1" >&2
	write_status failed "unexpected exit at line $1"
	exit 1
}

proxy_is_running() {
	[ "$(docker inspect -f '{{.State.Running}}' "$PROXY_CONTAINER" 2>/dev/null || true)" = "true" ]
}

web_is_healthy() {
	curl -sf --max-time 5 "$WEB_HEALTH_URL" >/dev/null 2>&1
}

vite_is_healthy() {
	curl -sf --max-time 5 "$VITE_HEALTH_URL" >/dev/null 2>&1
}

stack_is_healthy() {
	web_is_healthy && vite_is_healthy
}

STARTED_AT="$(now)"
trap 'on_unexpected_exit $LINENO' ERR

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
	echo "preview_already_launching"
	exit 0
fi

if stack_is_healthy && proxy_is_running; then
	write_status ready
	echo "preview_already_ready"
	exit 0
fi

write_status starting

[ -n "${MODAL_HOST:-}" ] || fail "MODAL_HOST is required"
[ -n "${PREVIEW_PORT:-}" ] || fail "PREVIEW_PORT is required"
[ -n "${REPO_PATH:-}" ] || fail "REPO_PATH is required"

cd "$REPO_PATH" || fail "repository checkout $REPO_PATH is missing"

cat >"$CADDYFILE" <<CADDY
{
	auto_https off
	admin off
}
:${PREVIEW_PORT} {
	@metrics path /_metrics /_metrics/*
	handle @metrics {
		respond 404
	}
	@vite_ws {
		header Connection *Upgrade*
		header Upgrade websocket
		query token=*
	}
	@vite {
		path /@*
		path /src/*
		path /node_modules/*
		path /public/*
		path /__vite_ping
	}
	handle @vite_ws {
		reverse_proxy 127.0.0.1:8234
	}
	handle @vite {
		reverse_proxy 127.0.0.1:8234 {
			header_up X-Forwarded-Proto https
		}
	}
	handle {
		reverse_proxy 127.0.0.1:8010 {
			header_up X-Forwarded-Proto https
		}
	}
}
CADDY

echo "== bootstrap-dev-stack =="
if [ -x /usr/local/bin/bootstrap-dev-stack ]; then
	/usr/local/bin/bootstrap-dev-stack || fail "bootstrap-dev-stack failed"
fi

echo "== preview proxy =="
if proxy_is_running; then
	echo "preview proxy already running"
else
	docker rm -f "$PROXY_CONTAINER" >/dev/null 2>&1 || true
	docker run -d --name "$PROXY_CONTAINER" --network host \
		-v "$CADDYFILE":/etc/caddy/Caddyfile:ro \
		caddy:latest caddy run -c /etc/caddy/Caddyfile ||
		fail "could not start the preview proxy"
fi

echo "== pnpm install =="
pnpm install --frozen-lockfile --prefer-offline || fail "pnpm install failed"

echo "== uv sync =="
uv sync || fail "uv sync failed"

activate_failed=
set +u
# shellcheck disable=SC1091
source .venv/bin/activate || activate_failed=1
set -u
[ -z "$activate_failed" ] || fail "could not activate the python environment"

export MODAL_HOST
export CADDY_HOST=:8000
export SITE_URL="https://$MODAL_HOST"
export JS_URL="https://$MODAL_HOST:443"
export VITE_ALLOWED_HOSTS="$MODAL_HOST"
export IS_BEHIND_PROXY=1
export TRUST_ALL_PROXIES=1
export DEBUG=1
export COMPOSE_PROJECT_NAME=posthog
export HOGLI_SKIP_ZOMBIE_CHECK=1

echo "== hogli start =="
deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
hogli start -y -d || fail "hogli start failed"

echo "== hogli wait =="
hogli wait --timeout "$HEALTH_TIMEOUT_SECONDS" || fail "a dev stack process crashed or did not become ready within ${HEALTH_TIMEOUT_SECONDS}s"

echo "== waiting for the web server and vite =="
stack_ready=0
deadline=$((deadline + 60))
while [ "$SECONDS" -lt "$deadline" ]; do
	if stack_is_healthy; then
		stack_ready=1
		break
	fi
	sleep 3
done
if [ "$stack_ready" -ne 1 ]; then
	web_is_healthy || fail "the web server did not answer /_health within ${HEALTH_TIMEOUT_SECONDS}s"
	fail "vite did not serve /@vite/client within ${HEALTH_TIMEOUT_SECONDS}s"
fi

echo "== setup_dev =="
python manage.py setup_dev --no-data || echo "setup_dev failed; the preview has no seeded login"

write_status ready
echo "preview_ready"
