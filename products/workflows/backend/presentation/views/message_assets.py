from rest_framework import serializers


class MessageAssetSerializer(serializers.Serializer):
    invocation_id = serializers.CharField(help_text="The workflow run this email was sent in.")
    action_id = serializers.CharField(
        help_text="The email step (action node) within the workflow that sent this email."
    )
    function_id = serializers.CharField(
        help_text="The workflow id that sent this email — used to navigate from a person's "
        "Emails tab back into the originating workflow."
    )
    function_name = serializers.CharField(
        help_text="Human-readable workflow name for display. Empty when the workflow has been deleted; "
        "clients should fall back to function_id in that case.",
        allow_blank=True,
    )
    parent_run_id = serializers.CharField(
        help_text="The batch run this email belongs to, for batch-triggered workflows. Empty for event-triggered runs."
    )
    kind = serializers.CharField(
        help_text="Message channel this asset was sent on: 'email' or 'push'. The per-person endpoints "
        "return one channel each."
    )
    distinct_id = serializers.CharField(help_text="The recipient's distinct_id.")
    person_id = serializers.CharField(help_text="The recipient's person UUID, if resolved.")
    recipient = serializers.CharField(
        help_text="Who the message went to: the email address for 'email', or the recipient's distinct ID for 'push'."
    )
    subject = serializers.CharField(help_text="The email subject line, or the push notification title.")
    status = serializers.CharField(
        help_text="Delivery status at capture time. Currently always 'sent' - only delivered messages are captured."
    )
    sent_at = serializers.DateTimeField(help_text="When the message was sent.")


class MessageAssetsRequestSerializer(serializers.Serializer):
    parent_run_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Only return assets for this batch run (HogFlowBatchJob id). Pass an empty string to return only "
        "event-triggered (non-batch) assets; omit to return all.",
    )
    action_id = serializers.CharField(
        required=False,
        help_text="Only return assets sent by this email step (action node id) — used to drill in from a step's metric.",
    )
    invocation_id = serializers.CharField(
        required=False,
        help_text="Only return the asset for this specific workflow run — used to deep-link from a single log entry "
        "to the email it sent. Returns 0 rows when the send had no captured asset (text-only, kill-switch off, "
        "or standalone email).",
    )
    distinct_id = serializers.CharField(
        required=False,
        help_text="Only return assets sent to this distinct_id.",
    )
    search = serializers.CharField(
        required=False,
        help_text="Case-insensitive substring match on recipient email or subject.",
    )
    after = serializers.CharField(
        required=False,
        default="-30d",
        help_text="Start of the time range, matched on sent time. Relative ('-30d', '-24h') or ISO 8601. "
        "Defaults to -30d (the retention window) — bounds the ClickHouse partition scan.",
    )
    before = serializers.CharField(
        required=False,
        help_text="End of the time range, matched on sent time. Same format as 'after'. Defaults to now.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=50,
        max_value=500,
        min_value=1,
        help_text="Maximum number of assets to return (1-500, default 50).",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of assets to skip, for pagination.",
    )


class MessageAssetContentRequestSerializer(serializers.Serializer):
    invocation_id = serializers.CharField(help_text="The workflow run the email was sent in.")
    action_id = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="The email step (action node) that sent the email. Defaults to empty for standalone email sends.",
    )


class PersonMessageAssetsRequestSerializer(serializers.Serializer):
    after = serializers.CharField(
        required=False,
        default="-30d",
        help_text="Start of the time range, matched on sent time. Relative ('-30d', '-24h') or ISO 8601. "
        "Defaults to -30d (the retention window) — bounds the ClickHouse partition scan.",
    )
    before = serializers.CharField(
        required=False,
        help_text="End of the time range, matched on sent time. Same format as 'after'. Defaults to now.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=50,
        max_value=500,
        min_value=1,
        help_text="Maximum number of assets to return (1-500, default 50).",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of assets to skip, for pagination.",
    )
