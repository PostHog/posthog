FIELD_EXCLUSIONS = {
    "ExternalDataSource": [
        "connection_id",
        "destination_id",
        "are_tables_created",
        # Reverse relation to a fail-closed model: reading through it in `changes_between` raises
        # TeamScopeError when a source is saved outside request scope, and it isn't source-config intent.
        "custom_oauth2_integrations",
        # Same hazard: the destination set is edited through its own endpoint, not by saving a source.
        "destination_links",
        # The diff reads each reverse relation in full on both sides, after the save, so it never
        # sees a real before-state. The view prefetches `schemas` without the deleted ones, so the
        # two lists differ on every save and the entry stores every job and schema twice, which
        # goes past the Kafka message limit for a source with a long sync history. Schemas log
        # their own changes under the ExternalDataSchema scope, and jobs are sync runs, not user changes.
        "jobs",
        "schemas",
    ],
    "ExternalDataSchema": [
        "status",
        "sync_type_config",
        "latest_error",
        "last_synced_at",
        # Reverse relation to a fail-closed model — same hazard as the source's `destination_links`.
        # Every sync saves the schema from a Temporal activity, where diffing it would raise.
        "destination_links",
        # Pipeline-assigned, not user intent. Diffing it resolves the FK through
        # DataWarehouseTable.objects, whose manager adds two joins and a prefetch on every
        # schema save (even ones that don't touch this field) — the extra queries have
        # deadlocked with concurrent DDL in production.
        "table",
        # Written by the model on the stop-syncing transition to record whether PostHog halted
        # the schema itself, so it is derived state and not user intent. Diffing it also puts a
        # second change on the entry that turns syncing on or off, which makes the schema
        # activity feed read "updated schema" in place of "enabled schema".
        "auto_disabled_at",
        # Derived from full_refresh_interval_days and moved by every full resync, so it is not user intent.
        "next_full_refresh_at",
    ],
}


FIELD_NAME_OVERRIDES = {
    "ExternalDataSource": {
        "job_inputs": "configuration",
    },
    "ExternalDataSchema": {
        "should_sync": "enabled",
        "live_query_enabled": "live queries",
        "masked_columns": "masked columns",
        "full_refresh_interval_days": "full refresh interval (days)",
        "full_refresh_time_of_day": "full refresh time (UTC)",
    },
}


FIELD_WITH_MASKED_CONTENTS = {
    "ExternalDataSource": [
        "job_inputs",
    ],
}
