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
PREVIEW_LOGIN_EMAIL=test@posthog.com
PREVIEW_LOGIN_PASSWORD=12345678

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

proxy_is_healthy() {
	curl -sf --max-time 5 "http://127.0.0.1:${PREVIEW_PORT}/_health" >/dev/null 2>&1
}

probe() {
	PROBE_STEP="$1"
	PROBE_CODE="$(curl -s --max-time 30 -o /dev/null -w '%{http_code}' "${@:2}")"
	case "$PROBE_CODE" in 2*) return 0 ;; *) return 1 ;; esac
}

app_is_usable() {
	jar="$(mktemp)"
	base="http://127.0.0.1:${PREVIEW_PORT}"
	probe login -H "Host: $MODAL_HOST" -c "$jar" "$base/login" || return 1
	csrf="$(awk '/csrftoken/ {print $7}' "$jar" | tail -n1)"
	probe api_login -H "Host: $MODAL_HOST" -b "$jar" -c "$jar" -H 'Content-Type: application/json' \
		-H "X-CSRFToken: $csrf" -H "Origin: https://$MODAL_HOST" -H "Referer: https://$MODAL_HOST/" \
		-d "{\"email\":\"$PREVIEW_LOGIN_EMAIL\",\"password\":\"$PREVIEW_LOGIN_PASSWORD\"}" "$base/api/login/" || return 1
	probe projects -H "Host: $MODAL_HOST" -b "$jar" "$base/api/projects/@current/" || return 1
	rm -f "$jar"
}

preview_is_ready() {
	stack_is_healthy && proxy_is_running && proxy_is_healthy && app_is_usable
}

STARTED_AT="$(now)"
trap 'on_unexpected_exit $LINENO' ERR

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
	echo "preview_already_launching"
	exit 0
fi

[ -n "${MODAL_HOST:-}" ] || fail "MODAL_HOST is required"
[ -n "${PREVIEW_PORT:-}" ] || fail "PREVIEW_PORT is required"
[ -n "${REPO_PATH:-}" ] || fail "REPO_PATH is required"

if preview_is_ready; then
	write_status ready
	echo "preview_already_ready"
	exit 0
fi

write_status starting

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
	/usr/local/bin/bootstrap-dev-stack 9>&- || fail "bootstrap-dev-stack failed"
fi

echo "== preview proxy =="
if proxy_is_running; then
	echo "preview proxy already running"
else
	docker rm -f "$PROXY_CONTAINER" >/dev/null 2>&1 || true
	docker run -d --name "$PROXY_CONTAINER" --network host --restart unless-stopped \
		-v "$CADDYFILE":/etc/caddy/Caddyfile:ro \
		caddy:2 caddy run -c /etc/caddy/Caddyfile ||
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
export HOGLI_SKIP_PREVIEW_CHECK=1

echo "== hogli start =="
start_lock_deadline=$((SECONDS + 120))
until flock -n "$REPO_PATH/bin/start.lock" true 2>/dev/null; do
	[ "$SECONDS" -lt "$start_lock_deadline" ] || break
	echo "another bin/start is running; waiting for it"
	sleep 2
done
hogli start -y -d || echo "hogli start did not start a new stack; waiting for the existing one"

echo "== hogli wait =="
hogli wait --timeout "$HEALTH_TIMEOUT_SECONDS" || fail "a dev stack process crashed or did not become ready within ${HEALTH_TIMEOUT_SECONDS}s"

echo "== waiting for the web server, vite and the preview proxy =="
deadline=$((SECONDS + 60))
until stack_is_healthy; do
	[ "$SECONDS" -lt "$deadline" ] || break
	sleep 3
done
web_is_healthy || fail "the web server did not answer /_health after hogli wait"
vite_is_healthy || fail "vite did not serve /@vite/client after hogli wait"
proxy_is_healthy || fail "the preview proxy did not answer on port ${PREVIEW_PORT}: $(docker logs --tail 5 "$PROXY_CONTAINER" 2>&1 || true)"

echo "== login probe =="
if ! app_is_usable; then
	echo "== setup_dev =="
	python manage.py setup_dev --no-data || fail "setup_dev failed; the preview has no seeded login"
	app_is_usable || fail "login probe failed at $PROBE_STEP through the preview proxy (HTTP $PROBE_CODE)"
fi

write_status ready
echo "preview_ready"
