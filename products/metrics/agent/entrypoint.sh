#!/bin/sh
# Renders the OpenTelemetry Collector config for the PostHog metrics agent,
# then execs the collector. See README.md for the env var surface.
#
# Config resolution order. Sources are additive: prometheus scraping and
# Google Cloud Monitoring can both feed the same pipeline.
#   1. $CONFIG_DIR/config.yaml            - full config override, used verbatim
#   2. $CONFIG_DIR/scrape_configs.yaml    - custom scrape_configs spliced into the template
#   3. SCRAPE_TARGETS env var             - static scrape job rendered from env
#   4. $CONFIG_DIR/gcp_metrics_list.yaml  - custom metrics_list for the GCM receiver
#   5. GCP_PROJECT_ID + GCP_METRICS / GCP_METRIC_FILTERS - GCM receiver rendered from env
#
# Scalar values (API key, host, interval, ...) are left as ${env:VAR} references
# for the collector's native config substitution, so secrets never pass through
# this script. Only the scrape_configs and metrics_list block structures are
# rendered here, because env substitution cannot expand a comma-separated
# string into a YAML list.
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

PROM_SNIPPET=$(mktemp)
GCP_SNIPPET=$(mktemp)
trap 'rm -f "$PROM_SNIPPET" "$GCP_SNIPPET"' EXIT

# Double single quotes so a value stays valid inside YAML single quotes.
yaml_squote() {
    printf '%s' "$1" | sed "s/'/''/g"
}

# --- prometheus source ---
if [ -f "$CONFIG_DIR/scrape_configs.yaml" ]; then
    # Re-indent the mounted scrape_configs list under the prometheus receiver.
    {
        printf '%s\n' '    prometheus:' '        config:' '            scrape_configs:'
        awk '{ if ($0 == "") print ""; else print "                " $0 }' \
            "$CONFIG_DIR/scrape_configs.yaml"
    } >"$PROM_SNIPPET"
elif [ -n "${SCRAPE_TARGETS:-}" ]; then
    TARGETS=""
    OLDIFS=$IFS
    IFS=,
    for target in $SCRAPE_TARGETS; do
        target=$(printf '%s' "$target" | sed 's/^ *//;s/ *$//')
        [ -n "$target" ] || continue
        target=$(yaml_squote "$target")
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

    cat >"$PROM_SNIPPET" <<EOF
    prometheus:
        config:
            scrape_configs:
                - job_name: '\${env:SCRAPE_JOB_NAME:-posthog-metrics-agent}'
                  scrape_interval: '\${env:SCRAPE_INTERVAL:-15s}'
                  metrics_path: '\${env:SCRAPE_METRICS_PATH:-/metrics}'
                  # OpenMetrics first so exemplars (trace links) survive the scrape.
                  scrape_protocols: [OpenMetricsText1.0.0, OpenMetricsText0.0.1, PrometheusText0.0.4]
                  static_configs:
                      - targets: [$TARGETS]
EOF

    if [ "$SHARD_COUNT" -gt 1 ]; then
        cat >>"$PROM_SNIPPET" <<EOF
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

PROM_ENABLED=0
[ -s "$PROM_SNIPPET" ] && PROM_ENABLED=1

# --- google cloud monitoring source ---
GCP_ENABLED=0
if [ -n "${GCP_PROJECT_ID:-}" ]; then
    GCP_ENABLED=1
fi
if [ "$GCP_ENABLED" -eq 0 ] && {
    [ -n "${GCP_METRICS:-}" ] || [ -n "${GCP_METRIC_FILTERS:-}" ] || [ -f "$CONFIG_DIR/gcp_metrics_list.yaml" ]
}; then
    echo "error: GCP_PROJECT_ID is required when GCP_METRICS or GCP_METRIC_FILTERS is set" \
        "or $CONFIG_DIR/gcp_metrics_list.yaml is mounted" >&2
    exit 1
fi
if [ "$GCP_ENABLED" -eq 1 ]; then
    if [ "$SHARD_COUNT" -gt 1 ]; then
        echo "error: GCP_PROJECT_ID cannot be combined with SHARD_COUNT > 1" \
            "(every shard would pull the same Cloud Monitoring series);" \
            "run a separate single-instance agent for Google Cloud Monitoring" >&2
        exit 1
    fi
    if [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ] && [ ! -r "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
        echo "error: GOOGLE_APPLICATION_CREDENTIALS points to '$GOOGLE_APPLICATION_CREDENTIALS'" \
            "which is missing or not readable by uid 10001" >&2
        exit 1
    fi

    cat >"$GCP_SNIPPET" <<EOF
    googlecloudmonitoring:
        project_id: '\${env:GCP_PROJECT_ID}'
        collection_interval: '\${env:GCP_COLLECTION_INTERVAL:-60s}'
        metrics_list:
EOF
    if [ -f "$CONFIG_DIR/gcp_metrics_list.yaml" ]; then
        # Re-indent the mounted metrics_list under the receiver.
        awk '{ if ($0 == "") print ""; else print "            " $0 }' \
            "$CONFIG_DIR/gcp_metrics_list.yaml" >>"$GCP_SNIPPET"
    else
        if [ -n "${GCP_METRICS:-}" ]; then
            OLDIFS=$IFS
            IFS=,
            for metric in $GCP_METRICS; do
                metric=$(printf '%s' "$metric" | sed 's/^ *//;s/ *$//')
                [ -n "$metric" ] || continue
                printf "            - metric_name: '%s'\n" "$(yaml_squote "$metric")" >>"$GCP_SNIPPET"
            done
            IFS=$OLDIFS
        fi
        if [ -n "${GCP_METRIC_FILTERS:-}" ]; then
            # Filters can contain commas (one_of("a", "b")), so they split on
            # semicolons, which never appear in the filter grammar.
            OLDIFS=$IFS
            IFS=';'
            for filter in $GCP_METRIC_FILTERS; do
                filter=$(printf '%s' "$filter" | sed 's/^ *//;s/ *$//')
                [ -n "$filter" ] || continue
                printf "            - metric_descriptor_filter: '%s'\n" "$(yaml_squote "$filter")" >>"$GCP_SNIPPET"
            done
            IFS=$OLDIFS
        fi
        if ! grep -q 'metric_' "$GCP_SNIPPET"; then
            echo "error: GCP_METRICS or GCP_METRIC_FILTERS is required with GCP_PROJECT_ID" \
                "(or mount $CONFIG_DIR/gcp_metrics_list.yaml)" >&2
            exit 1
        fi
    fi
fi

if [ "$PROM_ENABLED" -eq 0 ] && [ "$GCP_ENABLED" -eq 0 ]; then
    echo "error: SCRAPE_TARGETS is required (comma-separated host:port list)," \
        "unless you mount $CONFIG_DIR/scrape_configs.yaml or $CONFIG_DIR/config.yaml," \
        "or set GCP_PROJECT_ID to pull from Google Cloud Monitoring" >&2
    exit 1
fi

DEBUG_ENABLED=0
case "${POSTHOG_DEBUG:-}" in
    1 | true | TRUE | yes) DEBUG_ENABLED=1 ;;
esac

PERSIST_ENABLED=0
case "${PERSIST_QUEUE:-}" in
    1 | true | TRUE | yes) PERSIST_ENABLED=1 ;;
esac

awk -v prom="$PROM_SNIPPET" -v gcp="$GCP_SNIPPET" -v prom_on="$PROM_ENABLED" -v gcp_on="$GCP_ENABLED" \
    -v debug="$DEBUG_ENABLED" -v persist="$PERSIST_ENABLED" '
    function splice(file) {
        while ((getline line < file) > 0) print line
        close(file)
    }
    $0 == "#__PROMETHEUS_RECEIVER__" {
        if (prom_on == "1") splice(prom)
        next
    }
    $0 == "#__GCP_RECEIVER__" {
        if (gcp_on == "1") splice(gcp)
        next
    }
    $0 == "#__GCP_RESOURCE_PROCESSOR__" {
        if (gcp_on == "1") {
            print "    # Cloud Monitoring resources carry no service.name; give them one so they"
            print "    # group in the Metrics UI. `insert` never overrides a scraped job_name."
            print "    resource/gcp:"
            print "        attributes:"
            print "            - key: service.name"
            print "              value: \x27${env:GCP_SERVICE_NAME:-google-cloud-monitoring}\x27"
            print "              action: insert"
        }
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
    index($0, "__PIPELINE_RECEIVERS__") {
        if (prom_on == "1" && gcp_on == "1") {
            receivers = "prometheus, googlecloudmonitoring"
        } else if (gcp_on == "1") {
            receivers = "googlecloudmonitoring"
        } else {
            receivers = "prometheus"
        }
        sub(/__PIPELINE_RECEIVERS__/, receivers)
        print
        next
    }
    index($0, "__PIPELINE_PROCESSORS__") {
        processors = (gcp_on == "1") ? "memory_limiter, resource/gcp, batch" : "memory_limiter, batch"
        sub(/__PIPELINE_PROCESSORS__/, processors)
        print
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
