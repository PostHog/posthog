#!/usr/bin/env python3
"""
Pre-provisions all required Kafka topics for PostHog and PostHog test runs.
Compatible with Tansu and Redpanda. Uses confluent_kafka for fast, reliable topic management.
"""
import sys
import time
from confluent_kafka.admin import AdminClient, NewTopic

BASE_TOPICS = [
    "clickhouse_events_json",
    "exceptions_ingestion",
    "events_plugin_ingestion",
    "events_plugin_ingestion_overflow",
    "events_plugin_ingestion_historical",
    "clickhouse_person",
    "clickhouse_person_unique_id",
    "clickhouse_person_distinct_id",
    "clickhouse_performance_events",
    "plugin_log_entries",
    "events_dead_letter_queue",
    "clickhouse_groups",
    "clickhouse_ingestion_warnings",
    "clickhouse_app_metrics",
    "clickhouse_app_metrics2",
    "clickhouse_metrics_time_to_see_data",
    "clickhouse_person_override",
    "log_entries",
    "log_entries_v2_test",
    "clickhouse_hog_invocation_results",
    "clickhouse_message_assets",
    "clickhouse_heatmap_events",
    "clickhouse_ai_events_json",
    "clickhouse_flag_evaluations",
    "session_recording_events",
    "clickhouse_session_replay_events",
    "clickhouse_session_replay_features",
    "clickhouse_session_recording_events",
    "clickhouse_error_tracking_issue_fingerprint",
    "clickhouse_error_tracking_fingerprint_issue_state",
    "clickhouse_error_tracking_issue_fingerprint_embeddings",
    "clickhouse_document_embeddings",
    "document_embeddings_input",
    "document_embedding_results",
    "cdp_internal_events",
    "cdp_backfill_events",
    "cohort_membership_changed",
    "cdp_data_warehouse_source_table",
    "data_warehouse_source_webhooks",
    "data_warehouse_source_webhooks_dlq",
    "clickhouse_tophog",
    "clickhouse_billing_usage_records",
    "distinct_id_usage_events_json",
    "clickhouse_property_values",
    "clickhouse_precalculated_person_properties",
    "clickhouse_prefiltered_events",
    "notification_events",
    "signals_report_completed",
    "flags_cache_invalidation",
    "flags_cache_invalidation_dlq",
    "warehouse_person_property_updates",
    "warehouse_person_property_updates_dlq",
    "logs_ingestion",
    "logs_ingestion_dlq",
    "ingestion-traces",
    "ingestion-traces-dlq",
]

TARGET_PARTITIONS = 16


def main():
    broker = "127.0.0.1:19092"
    if len(sys.argv) > 1:
        broker = sys.argv[1]

    try:
        admin = AdminClient({"bootstrap.servers": broker, "socket.timeout.ms": 5000})
    except Exception as e:
        print(f"Warning: Could not connect to Kafka broker at {broker}: {e}", file=sys.stderr)
        return

    try:
        md = admin.list_topics(timeout=5)
        existing = md.topics
    except Exception as e:
        print(f"Warning: Could not list topics: {e}", file=sys.stderr)
        existing = {}

    needed = set(BASE_TOPICS)
    for t in BASE_TOPICS:
        needed.add(f"{t}_test")
        for gw in range(16):
            needed.add(f"{t}_test_gw{gw}")

    # Check for topics that need partition expansion or creation
    underpartitioned = [
        t for t in needed
        if t in existing and len(existing[t].partitions) < TARGET_PARTITIONS
    ]
    missing = [t for t in needed if t not in existing]

    if underpartitioned:
        print(f"Deleting {len(underpartitioned)} underpartitioned topics to re-create with {TARGET_PARTITIONS} partitions...")
        del_futures = admin.delete_topics(underpartitioned)
        for t, f in del_futures.items():
            try:
                f.result(timeout=5)
            except Exception:
                pass
        time.sleep(0.3)
        missing.extend(underpartitioned)

    if not missing:
        print(f"All {len(needed)} Kafka topics exist with >= {TARGET_PARTITIONS} partitions.")
        return

    print(f"Provisioning {len(missing)} Kafka topics ({TARGET_PARTITIONS} partitions) on {broker}...")
    to_create = [NewTopic(t, num_partitions=TARGET_PARTITIONS, replication_factor=1) for t in missing]
    create_futures = admin.create_topics(to_create)
    success = 0
    for t, f in create_futures.items():
        try:
            f.result(timeout=5)
            success += 1
        except Exception as e:
            print(f"Notice creating topic {t}: {e}", file=sys.stderr)
    print(f"Successfully provisioned {success}/{len(missing)} topics.")


if __name__ == "__main__":
    main()
