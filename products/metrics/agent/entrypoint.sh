#!/bin/sh
# Renders the OpenTelemetry Collector config for the PostHog metrics agent,
# then execs the collector. See README.md for the env var surface.
#
# Config resolution order:
#   1. $CONFIG_DIR/config.yaml          - full config override, used verbatim
#   2. $CONFIG_DIR/scrape_configs.yaml  - custom scrape_configs spliced into the template
#   3. SCRAPE_TARGETS env var           - static scrape job rendered from env
#
# Scalar values (API key, host, interval, ...) are left as ${env:VAR} references
# for the collector's native config substitution, so secrets never pass through
# this script. Only the scrape_configs block structure is rendered here, because
# env substitution cannot expand a comma-separated string into a YAML list.
#
# RENDER_ONLY=1 prints the resolved config and exits (used by tests/render).
set -eu

CONFIG_DIR="${CONFIG_DIR:-/etc/posthog}"
TEMPLATE="$CONFIG_DIR/config.yaml.tmpl"
RENDERED="${RENDERED_CONFIG:-/tmp/config.yaml}"
OTELCOL="${OTELCOL_BIN:-/usr/local/bin/otelcol-contrib}"

finish() {
    if [ "${RENDER_ONLY:-}" = "1" ]; then
        cat "$1"
        exit 0
    fi
    exec "$OTELCOL" --config "$1"
}

if [ -f "$CONFIG_DIR/config.yaml" ]; then
    finish "$CONFIG_DIR/config.yaml"
fi

if [ -z "${POSTHOG_API_KEY:-}" ]; then
    echo "error: POSTHOG_API_KEY is required (your PostHog project API key)" >&2
    exit 1
fi

SNIPPET=$(mktemp)
trap 'rm -f "$SNIPPET"' EXIT

if [ -f "$CONFIG_DIR/scrape_configs.yaml" ]; then
    # Re-indent the mounted scrape_configs list under the prometheus receiver.
    awk '{ if ($0 == "") print ""; else print "                " $0 }' \
        "$CONFIG_DIR/scrape_configs.yaml" >"$SNIPPET"
else
    if [ -z "${SCRAPE_TARGETS:-}" ]; then
        echo "error: SCRAPE_TARGETS is required (comma-separated host:port list)," \
            "unless you mount $CONFIG_DIR/scrape_configs.yaml or $CONFIG_DIR/config.yaml" >&2
        exit 1
    fi

    TARGETS=""
    OLDIFS=$IFS
    IFS=,
    for target in $SCRAPE_TARGETS; do
        target=$(printf '%s' "$target" | sed 's/^ *//;s/ *$//')
        [ -n "$target" ] || continue
        # Double single quotes so the target stays valid inside YAML quotes.
        target=$(printf '%s' "$target" | sed "s/'/''/g")
        if [ -n "$TARGETS" ]; then
            TARGETS="$TARGETS, '$target'"
        else
            TARGETS="'$target'"
        fi
    done
    IFS=$OLDIFS

    if [ -z "$TARGETS" ]; then
        echo "error: SCRAPE_TARGETS contained no targets" >&2
        exit 1
    fi

    cat >"$SNIPPET" <<EOF
                - job_name: '\${env:SCRAPE_JOB_NAME:-posthog-metrics-agent}'
                  scrape_interval: '\${env:SCRAPE_INTERVAL:-15s}'
                  metrics_path: '\${env:SCRAPE_METRICS_PATH:-/metrics}'
                  # OpenMetrics first so exemplars (trace links) survive the scrape.
                  scrape_protocols: [OpenMetricsText1.0.0, OpenMetricsText0.0.1, PrometheusText0.0.4]
                  static_configs:
                      - targets: [$TARGETS]
EOF
fi

DEBUG_ENABLED=0
case "${POSTHOG_DEBUG:-}" in
    1 | true | TRUE | yes) DEBUG_ENABLED=1 ;;
esac

awk -v snippet="$SNIPPET" -v debug="$DEBUG_ENABLED" '
    $0 == "#__SCRAPE_CONFIGS__" {
        while ((getline line < snippet) > 0) print line
        close(snippet)
        next
    }
    $0 == "#__DEBUG_EXPORTER__" {
        if (debug == "1") {
            print "    debug:"
            print "        verbosity: detailed"
        }
        next
    }
    index($0, "__PIPELINE_EXPORTERS__") {
        exporters = (debug == "1") ? "otlphttp, debug" : "otlphttp"
        sub(/__PIPELINE_EXPORTERS__/, exporters)
        print
        next
    }
    { print }
' "$TEMPLATE" >"$RENDERED"

finish "$RENDERED"
