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

# Sharding: with SHARD_COUNT set, each instance keeps only the targets that
# hash to its SHARD_INDEX, so a fleet partitions the target set with no
# coordination. The index falls back to the hostname's trailing ordinal
# (StatefulSet pods are named <name>-<ordinal>), matching how vmagent shards.
# Resolved before any config path so mounted configs can reference
# ${env:SHARD_INDEX} too.
SHARD_COUNT="${SHARD_COUNT:-1}"
case "$SHARD_COUNT" in
    '' | *[!0-9]*)
        echo "error: SHARD_COUNT must be a positive integer, got '$SHARD_COUNT'" >&2
        exit 1
        ;;
esac
if [ "$SHARD_COUNT" -gt 1 ]; then
    if [ -z "${SHARD_INDEX:-}" ]; then
        host="${HOSTNAME:-$(hostname)}"
        SHARD_INDEX=$(printf '%s' "$host" | sed -n 's/.*-\([0-9][0-9]*\)$/\1/p')
        if [ -z "$SHARD_INDEX" ]; then
            echo "error: SHARD_INDEX is not set and cannot be derived from hostname '$host'" \
                "(expected a trailing -<ordinal>, e.g. a StatefulSet pod name)" >&2
            exit 1
        fi
    fi
    case "$SHARD_INDEX" in
        '' | *[!0-9]*)
            echo "error: SHARD_INDEX must be a non-negative integer, got '$SHARD_INDEX'" >&2
            exit 1
            ;;
    esac
    if [ "$SHARD_INDEX" -ge "$SHARD_COUNT" ]; then
        echo "error: SHARD_INDEX must be less than SHARD_COUNT ($SHARD_INDEX >= $SHARD_COUNT)" >&2
        exit 1
    fi
    export SHARD_INDEX
fi

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

    if [ "$SHARD_COUNT" -gt 1 ]; then
        cat >>"$SNIPPET" <<EOF
                  # Shard $SHARD_INDEX of $SHARD_COUNT: keep only targets that hash to this shard.
                  relabel_configs:
                      - source_labels: [__address__]
                        modulus: $SHARD_COUNT
                        target_label: __tmp_shard
                        action: hashmod
                      - source_labels: [__tmp_shard]
                        regex: '$SHARD_INDEX'
                        action: keep
EOF
    fi
fi

DEBUG_ENABLED=0
case "${POSTHOG_DEBUG:-}" in
    1 | true | TRUE | yes) DEBUG_ENABLED=1 ;;
esac

PERSIST_ENABLED=0
case "${PERSIST_QUEUE:-}" in
    1 | true | TRUE | yes) PERSIST_ENABLED=1 ;;
esac

awk -v snippet="$SNIPPET" -v debug="$DEBUG_ENABLED" -v persist="$PERSIST_ENABLED" '
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
    $0 == "#__SENDING_QUEUE__" {
        if (persist == "1") {
            print "        sending_queue:"
            print "            enabled: true"
            print "            # Survives restarts: batches persist to disk until delivered."
            print "            storage: file_storage"
        }
        next
    }
    $0 == "#__FILE_STORAGE__" {
        if (persist == "1") {
            print "    file_storage:"
            print "        directory: \x27${env:QUEUE_DIR:-/var/lib/posthog-agent}\x27"
            print "        create_directory: true"
        }
        next
    }
    index($0, "__SERVICE_EXTENSIONS__") {
        extensions = (persist == "1") ? "health_check, file_storage" : "health_check"
        sub(/__SERVICE_EXTENSIONS__/, extensions)
        print
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
