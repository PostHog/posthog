#!/bin/sh
# Golden tests for entrypoint.sh config rendering.
# Usage: products/metrics/agent/tests/render/run.sh
# Each case runs the entrypoint with RENDER_ONLY=1 in a clean environment and
# diffs the rendered collector config against a golden file.
set -u
cd "$(dirname "$0")"
AGENT_DIR=$(cd ../.. && pwd)
PASS=0
FAIL=0

new_case_dir() {
    CASE_DIR=$(mktemp -d)
    cp "$AGENT_DIR/config/config.yaml.tmpl" "$CASE_DIR/"
}

# run_render <name> [VAR=value ...] — renders and diffs against golden/<name>.yaml
run_render() {
    name=$1
    shift
    out=$(mktemp)
    err=$(mktemp)
    if ! env -i PATH="$PATH" CONFIG_DIR="$CASE_DIR" RENDERED_CONFIG="$CASE_DIR/rendered.yaml" RENDER_ONLY=1 "$@" \
        sh "$AGENT_DIR/entrypoint.sh" >"$out" 2>"$err"; then
        echo "FAIL $name: entrypoint exited non-zero"
        cat "$err"
        FAIL=$((FAIL + 1))
        return
    fi
    if diff -u "golden/$name.yaml" "$out"; then
        echo "PASS $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL $name: rendered config differs from golden/$name.yaml"
        FAIL=$((FAIL + 1))
    fi
}

# expect_failure <name> <stderr needle> [VAR=value ...]
expect_failure() {
    name=$1
    needle=$2
    shift 2
    err=$(mktemp)
    if env -i PATH="$PATH" CONFIG_DIR="$CASE_DIR" RENDERED_CONFIG="$CASE_DIR/rendered.yaml" RENDER_ONLY=1 "$@" \
        sh "$AGENT_DIR/entrypoint.sh" >/dev/null 2>"$err"; then
        echo "FAIL $name: expected non-zero exit"
        FAIL=$((FAIL + 1))
        return
    fi
    if grep -q "$needle" "$err"; then
        echo "PASS $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL $name: stderr does not mention '$needle'"
        cat "$err"
        FAIL=$((FAIL + 1))
    fi
}

new_case_dir
run_render minimal POSTHOG_API_KEY=phc_test SCRAPE_TARGETS=app:9090

# Comma-separated targets with stray whitespace and an empty entry get trimmed.
new_case_dir
run_render multi POSTHOG_API_KEY=phc_test SCRAPE_TARGETS='app:9090, worker:9091 ,,db-exporter:9187'

new_case_dir
run_render debug POSTHOG_API_KEY=phc_test SCRAPE_TARGETS=app:9090 POSTHOG_DEBUG=1

# A mounted scrape_configs.yaml replaces the env-generated job verbatim
# (re-indented under the receiver), and SCRAPE_TARGETS is not required.
new_case_dir
cat >"$CASE_DIR/scrape_configs.yaml" <<'EOF'
- job_name: 'custom'
  scrape_interval: 30s
  static_configs:
      - targets: ['legacy:8080']
EOF
run_render mounted-scrape-configs POSTHOG_API_KEY=phc_test

# A mounted config.yaml wins over everything and is used verbatim; no env vars
# are required because the file may carry its own ${env:...} references.
new_case_dir
cp golden/full-override.yaml "$CASE_DIR/config.yaml"
run_render full-override

new_case_dir
expect_failure missing-api-key POSTHOG_API_KEY SCRAPE_TARGETS=app:9090

new_case_dir
expect_failure missing-targets SCRAPE_TARGETS POSTHOG_API_KEY=phc_test

new_case_dir
expect_failure empty-targets SCRAPE_TARGETS POSTHOG_API_KEY=phc_test SCRAPE_TARGETS=' , '

echo
echo "render tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
