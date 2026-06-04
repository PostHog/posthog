#!/usr/bin/env bash
# Containerized smoke test for the agent-sandbox-host image.
#
# Drives the built image the same way both production sandbox pools do:
# lays out /workdir/tools/<id>/compiled.js + /workdir/nonces.json, runs
# the container, exec's the dispatcher, asserts response shape. Fail-fast
# at the first wrong assertion.
#
# CI runs this after `docker build` and BEFORE `docker push` so a broken
# image never reaches GHCR.
#
# One scenario = one fresh container + fresh workdir. We tested re-using
# the same container across scenarios and hit a host-filesystem cache race
# on macOS bind mounts (request.json read returned stale bytes between
# writes). The per-scenario reset avoids the race entirely and matches the
# real DockerSandbox lifecycle anyway (one container per AgentSession).
#
# Usage:
#   scripts/smoke-test-image.sh [<image>]    default: posthog/agent-sandbox-host:dev

set -euo pipefail

IMAGE="${1:-posthog/agent-sandbox-host:dev}"
HERE="$(cd "$(dirname "$0")" && pwd)"

ECHO_TOOL='module.exports = {
    id: "echo",
    actions: {
        default: (args, ctx) => ({
            sum: args.a + args.b,
            secret_ref: ctx.secrets.ref("TEST_SECRET"),
            echoed: args.note,
        }),
    },
}'

# Run a single dispatch scenario:
#   $1 — request JSON
#   $2 — node assertion script (reads response.json from $1 argument)
# Spins up a fresh container + workdir, dispatches once, runs the assertion,
# tears down. The container is `docker run --rm` so cleanup is automatic.
run_scenario() {
    local request_json="$1"
    local assertion_script="$2"

    local workdir
    workdir="$(mktemp -d -t agent-sandbox-host-smoke.XXXXXX)"
    mkdir -p "$workdir/tools/echo"
    printf '%s' "$ECHO_TOOL" > "$workdir/tools/echo/compiled.js"
    echo '{ "type": "object" }' > "$workdir/tools/echo/schema.json"
    echo '{ "TEST_SECRET": "nonce_smoke_abc" }' > "$workdir/nonces.json"
    printf '%s' "$request_json" > "$workdir/request.json"
    # Bind-mounted dirs keep the host's UID/GID; the in-container `sandbox`
    # user can't write `host.alive` / `response.json` without help. macOS
    # Docker hides this via VirtioFS UID translation; Linux runners fail
    # closed. World-writable is fine — the test owns this dir end to end.
    chmod -R a+rwX "$workdir"

    local cid
    cid="$(docker run -d --rm --network=none \
        -v "$workdir:/workdir" \
        "$IMAGE" \
        node /sandbox/host.js)"

    local cleanup
    cleanup=$'docker rm -f '"$cid"' >/dev/null 2>&1 || true; rm -rf '"$workdir"
    trap "$cleanup" RETURN

    # Wait for host.alive — same gate the Docker pool uses.
    local deadline=$(( $(date +%s) + 5 ))
    while [ ! -f "$workdir/host.alive" ]; do
        if [ "$(date +%s)" -gt "$deadline" ]; then
            echo "smoke: FAIL — host.alive never appeared" >&2
            docker logs "$cid" >&2 || true
            return 1
        fi
        sleep 0.05
    done

    docker exec "$cid" \
        node /sandbox/dispatch.js /workdir/request.json /workdir/response.json

    node - "$workdir/response.json" <<<"$assertion_script"
}

echo "smoke: scenario 1 — happy path (echo)" >&2
run_scenario \
    '{"toolId":"echo","action":"default","args":{"a":2,"b":3,"note":"smoke"},"timeoutMs":10000}' \
    'const assert = require("node:assert/strict")
const res = JSON.parse(require("node:fs").readFileSync(process.argv[2], "utf-8"))
assert.equal(res.ok, true, `expected ok=true, got ${JSON.stringify(res)}`)
assert.deepEqual(res.result, { sum: 5, secret_ref: "nonce_smoke_abc", echoed: "smoke" })'

echo "smoke: scenario 2 — bad action on a real tool" >&2
run_scenario \
    '{"toolId":"echo","action":"nope","args":{},"timeoutMs":5000}' \
    'const assert = require("node:assert/strict")
const res = JSON.parse(require("node:fs").readFileSync(process.argv[2], "utf-8"))
assert.equal(res.ok, false, `expected ok=false, got ${JSON.stringify(res)}`)
assert.equal(res.error.code, "action_not_found", `wrong code: ${JSON.stringify(res)}`)'

echo "smoke: scenario 3 — unknown tool" >&2
run_scenario \
    '{"toolId":"no-such-tool","action":"default","args":{},"timeoutMs":5000}' \
    'const assert = require("node:assert/strict")
const res = JSON.parse(require("node:fs").readFileSync(process.argv[2], "utf-8"))
assert.equal(res.ok, false, `expected ok=false, got ${JSON.stringify(res)}`)
assert.equal(res.error.code, "tool_not_found", `wrong code: ${JSON.stringify(res)}`)'

echo "smoke: PASS — image $IMAGE works end-to-end" >&2
