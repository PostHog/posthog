import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional, cast

from rest_framework import serializers

from posthog.clickhouse.client.execute import sync_execute

# message_assets rows are written once per (invocation_id, action_id) but a retried
# Kafka produce can duplicate them, so collapse to the latest `version` the same way
# the invocation-results reader does. The argMax aliases are deliberately prefixed
# `latest_` so they never collide with a same-named raw column in a WHERE clause
# (ClickHouse would otherwise resolve the name to the aggregate and error).
_COLLAPSED_AGGREGATES = """
    invocation_id,
    action_id,
    argMax(parent_run_id, version) AS latest_parent_run_id,
    argMax(kind, version) AS latest_kind,
    argMax(distinct_id, version) AS latest_distinct_id,
    argMax(person_id, version) AS latest_person_id,
    argMax(recipient, version) AS latest_recipient,
    argMax(subject, version) AS latest_subject,
    argMax(status, version) AS latest_status,
    argMax(sent_at, version) AS latest_sent_at,
    argMax(s3_key, version) AS latest_s3_key,
    argMax(is_deleted, version) AS latest_is_deleted
""".strip()

_OUTER_COLUMNS = """
    invocation_id,
    action_id,
    latest_parent_run_id,
    latest_kind,
    latest_distinct_id,
    latest_person_id,
    latest_recipient,
    latest_subject,
    latest_status,
    latest_sent_at,
    latest_s3_key
""".strip()


@dataclasses.dataclass(frozen=True)
class MessageAsset:
    invocation_id: str
    action_id: str
    parent_run_id: str
    kind: str
    distinct_id: str
    person_id: str
    recipient: str
    subject: str
    status: str
    sent_at: datetime
    # Object-storage key for the rendered HTML. Used server-side to serve the
    # content; not exposed in the list response (see MessageAssetSerializer).
    s3_key: str


class MessageAssetSerializer(serializers.Serializer):
    invocation_id = serializers.CharField(help_text="The workflow run this email was sent in.")
    action_id = serializers.CharField(
        help_text="The email step (action node) within the workflow that sent this email."
    )
    parent_run_id = serializers.CharField(
        help_text="The batch run this email belongs to, for batch-triggered workflows. Empty for event-triggered runs."
    )
    kind = serializers.CharField(help_text="Asset kind. Currently always 'email'.")
    distinct_id = serializers.CharField(help_text="The recipient's distinct_id.")
    person_id = serializers.CharField(help_text="The recipient's person UUID, if resolved.")
    recipient = serializers.CharField(help_text="The recipient email address.")
    subject = serializers.CharField(help_text="The email subject line.")
    status = serializers.CharField(help_text="Delivery status at capture time. Currently always 'sent'.")
    sent_at = serializers.DateTimeField(help_text="When the email was sent.")


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


def _build_asset(row: tuple) -> MessageAsset:
    return MessageAsset(
        invocation_id=row[0],
        action_id=row[1],
        parent_run_id=row[2],
        kind=row[3],
        distinct_id=row[4],
        person_id=row[5],
        recipient=row[6],
        subject=row[7],
        status=row[8],
        sent_at=row[9],
        s3_key=row[10],
    )


def fetch_message_assets(
    team_id: int,
    function_kind: str,
    function_id: str,
    limit: int,
    offset: int = 0,
    parent_run_id: Optional[str] = None,
    action_id: Optional[str] = None,
    distinct_id: Optional[str] = None,
    search: Optional[str] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
) -> list[MessageAsset]:
    """List a workflow's sent-email assets, each collapsed to its latest version."""
    where = [
        "team_id = %(team_id)s",
        "function_kind = %(function_kind)s",
        "function_id = %(function_id)s",
    ]
    kwargs: dict[str, Any] = {
        "team_id": team_id,
        "function_kind": function_kind,
        "function_id": function_id,
        "limit": limit,
        "offset": offset,
    }

    # parent_run_id / distinct_id / recipient / subject are stable across an asset's
    # lifecycle rows, so they're filtered pre-aggregation on the raw columns (hitting
    # the bloom-filter skip indexes). `is_deleted` flips, so it's filtered post-collapse.
    if parent_run_id is not None:
        where.append("parent_run_id = %(parent_run_id)s")
        kwargs["parent_run_id"] = parent_run_id
    if action_id:
        where.append("action_id = %(action_id)s")
        kwargs["action_id"] = action_id
    if distinct_id:
        where.append("distinct_id = %(distinct_id)s")
        kwargs["distinct_id"] = distinct_id
    if search:
        where.append("(recipient ILIKE %(search)s OR subject ILIKE %(search)s)")
        kwargs["search"] = f"%{search}%"
    if after:
        where.append("sent_at >= toDateTime64(%(after)s, 6)")
        kwargs["after"] = after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if before:
        where.append("sent_at <= toDateTime64(%(before)s, 6)")
        kwargs["before"] = before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    query = f"""
        SELECT {_OUTER_COLUMNS}
        FROM (
            SELECT {_COLLAPSED_AGGREGATES}
            FROM message_assets
            WHERE {" AND ".join(where)}
            GROUP BY invocation_id, action_id
        )
        WHERE latest_is_deleted = 0
        ORDER BY latest_sent_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """

    results = cast(list, sync_execute(query, kwargs))
    return [_build_asset(row) for row in results]


def fetch_message_asset(
    team_id: int,
    function_kind: str,
    function_id: str,
    invocation_id: str,
    action_id: str,
) -> Optional[MessageAsset]:
    """Fetch a single asset by (invocation_id, action_id), including its storage key."""
    kwargs = {
        "team_id": team_id,
        "function_kind": function_kind,
        "function_id": function_id,
        "invocation_id": invocation_id,
        "action_id": action_id,
    }
    query = f"""
        SELECT {_OUTER_COLUMNS}
        FROM (
            SELECT {_COLLAPSED_AGGREGATES}
            FROM message_assets
            WHERE team_id = %(team_id)s
              AND function_kind = %(function_kind)s
              AND function_id = %(function_id)s
              AND invocation_id = %(invocation_id)s
              AND action_id = %(action_id)s
            GROUP BY invocation_id, action_id
        )
        WHERE latest_is_deleted = 0
    """

    results = cast(list, sync_execute(query, kwargs))
    if not results:
        return None
    return _build_asset(results[0])
