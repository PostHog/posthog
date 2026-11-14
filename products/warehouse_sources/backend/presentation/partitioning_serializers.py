"""Serializers for the partitioning policy, the repartition history and "repartition now"."""

from django.db import models

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.warehouse_sources.backend.facade.partitioning import PartitionPolicy, RepartitionStatus

PARTITION_POLICY_HELP_TEXT = (
    "Beta, available only when the partitioning controls feature is on for the project. How PostHog lays out "
    "this table's synced data in partitions, which trades query speed against sync speed. `auto` (the default) "
    "balances the two. `prefer_query_speed` keeps fewer, larger partitions, so queries read fewer files but "
    "merges during a sync are heavier. `prefer_sync_speed` keeps smaller partitions and never merges them back, "
    "so syncs are lighter but queries read more files. `manual` keeps the current layout until someone "
    "repartitions the table."
)


class RepartitionMode(models.TextChoices):
    DATETIME = "datetime", "Datetime"
    MD5 = "md5", "MD5"
    NUMERICAL = "numerical", "Numerical"


class RepartitionFormat(models.TextChoices):
    # Labels name the layout, which also keeps this set apart from other month/week/day/hour enums in the schema.
    MONTH = "month", "One partition per month"
    WEEK = "week", "One partition per week"
    DAY = "day", "One partition per day"
    HOUR = "hour", "One partition per hour"


class PartitionSchemeSerializer(serializers.Serializer):
    mode = serializers.CharField(
        allow_null=True, help_text="Partition mode: `datetime`, `md5` or `numerical`. `auto` or null means detected."
    )
    format = serializers.CharField(allow_null=True, help_text="Datetime tier: `month`, `week`, `day` or `hour`.")
    count = serializers.IntegerField(allow_null=True, help_text="Number of md5 buckets.")
    size = serializers.IntegerField(allow_null=True, help_text="Width of each numerical bucket.")
    keys = serializers.ListField(
        child=serializers.CharField(), allow_null=True, help_text="Columns the partition key is computed from."
    )


class PartitioningSummarySerializer(serializers.Serializer):
    policy = serializers.ChoiceField(choices=PartitionPolicy.choices, help_text=PARTITION_POLICY_HELP_TEXT)
    partition_mode = serializers.CharField(
        allow_null=True, help_text="Current partition mode, null before the first sync."
    )
    partition_format = serializers.CharField(allow_null=True, help_text="Current datetime tier, for datetime mode.")
    partition_count = serializers.IntegerField(allow_null=True, help_text="Current md5 bucket count, for md5 mode.")
    partition_size = serializers.IntegerField(allow_null=True, help_text="Current bucket width, for numerical mode.")
    partitioning_keys = serializers.ListField(
        child=serializers.CharField(), allow_null=True, help_text="Columns the partition key is computed from."
    )
    max_partition_bytes = serializers.IntegerField(
        allow_null=True, help_text="Size in bytes of the largest partition when the table was last measured."
    )
    healthy = serializers.BooleanField(
        allow_null=True,
        help_text="Whether the last measurement found nothing to change. Null before the first measurement.",
    )
    last_repartition_at = serializers.CharField(
        allow_null=True, help_text="ISO 8601 time of the last repartition, or of the last one the controller skipped."
    )
    repartition_pending = serializers.BooleanField(
        help_text="Whether a repartition is queued or running. The next sync runs a queued one."
    )


class RepartitionHistoryRowSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the history row.")
    status = serializers.ChoiceField(
        choices=RepartitionStatus.choices,
        help_text="`flagged`: queued for the next sync. `running`: the rewrite started. `completed`, `failed`, "
        "`skipped`: the outcome.",
    )
    trigger_reason = serializers.CharField(
        allow_null=True,
        help_text="Why it happened: `proactive_threshold` (largest partition over budget), `oom_history` (repeated "
        "out-of-memory kills), `coarsening` (too many small partitions), `user`, or `admin`.",
    )
    requested_by = UserBasicSerializer(allow_null=True, help_text="The user who asked for it, for `user` repartitions.")
    job_id = serializers.CharField(allow_null=True, help_text="ID of the sync job that ran or reported it.")
    scheme_before = PartitionSchemeSerializer(allow_null=True, help_text="Partition scheme before the rewrite.")
    scheme_after = PartitionSchemeSerializer(allow_null=True, help_text="Partition scheme the rewrite targets.")
    max_partition_bytes_before = serializers.IntegerField(
        allow_null=True, help_text="Size in bytes of the largest partition before the rewrite."
    )
    rows_rewritten = serializers.IntegerField(allow_null=True, help_text="Rows the completed rewrite wrote.")
    duration_seconds = serializers.FloatField(allow_null=True, help_text="How long the rewrite ran.")
    error_type = serializers.CharField(
        allow_null=True, help_text="For `failed`, the error type. For `skipped`, why nothing was rewritten."
    )
    created_at = serializers.DateTimeField(help_text="When the row was created.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="When it reached an outcome.")


class SyncStatsWindowSerializer(serializers.Serializer):
    start = serializers.DateTimeField(
        allow_null=True, help_text="Start of the window: when a repartition completed. Null before the first one."
    )
    end = serializers.DateTimeField(allow_null=True, help_text="End of the window. Null for the current layout.")
    repartition_id = serializers.UUIDField(
        allow_null=True, help_text="History row of the repartition that started the window."
    )
    job_count = serializers.IntegerField(
        help_text="Completed sync jobs in the window. Jobs that ran a rewrite are left out."
    )
    median_duration_seconds = serializers.FloatField(allow_null=True, help_text="Median sync job duration.")
    p90_duration_seconds = serializers.FloatField(allow_null=True, help_text="90th percentile sync job duration.")
    median_rows_per_second = serializers.FloatField(allow_null=True, help_text="Median rows synced per second.")


class PartitioningHistorySerializer(serializers.Serializer):
    summary = PartitioningSummarySerializer(help_text="The table's current partitioning.")
    repartitions = RepartitionHistoryRowSerializer(many=True, help_text="Repartitions of this table, newest first.")
    sync_windows = SyncStatsWindowSerializer(
        many=True,
        help_text="Sync stats for each layout the table had, oldest first. Compare windows to see how a "
        "repartition changed sync speed.",
    )


class RepartitionSchemaRequestSerializer(serializers.Serializer):
    partition_mode = serializers.ChoiceField(
        choices=RepartitionMode.choices,
        required=False,
        allow_null=True,
        help_text="Partition mode to rewrite into. Omit to keep the current mode.",
    )
    partition_format = serializers.ChoiceField(
        choices=RepartitionFormat.choices,
        required=False,
        allow_null=True,
        help_text="Datetime tier. Required for `datetime` mode. A coarser tier means fewer, larger partitions.",
    )
    partition_count = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Number of md5 buckets. Required for `md5` mode.",
    )
    partition_size = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Width of each numerical bucket. Required for `numerical` mode.",
    )
    partitioning_keys = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Columns to compute the partition key from. Omit to keep the current keys. `datetime` and "
        "`numerical` take exactly one column, and need it when the mode changes.",
    )


class RepartitionSchemaResponseSerializer(serializers.Serializer):
    message = serializers.CharField(help_text="What was staged, and whether a run started.")
    run_started = serializers.BooleanField(
        help_text="Whether a run that rewrites the table started now. When false, the next sync runs it."
    )
    partition_policy = serializers.ChoiceField(
        choices=PartitionPolicy.choices,
        help_text="The table's policy after the request. A repartition sets it to `manual`, so PostHog keeps the "
        "chosen layout.",
    )


class RepartitionErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the repartition was refused.")
    code = serializers.CharField(
        help_text="`invalid_scheme`, `over_budget`, `unknown_size`, `unsupported`, `busy`, `cooldown`, "
        "`read_failed` or `pause_failed`."
    )
