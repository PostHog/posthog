import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional, cast

from rest_framework import serializers

from posthog.clickhouse.client.execute import sync_execute

# `latest_` prefix on the argMax aliases prevents collision with the raw column
# names in any outer WHERE — ClickHouse resolves the bare name to the aggregate
# and errors otherwise.
_COLLAPSED_AGGREGATES = """
    invocation_id,
    action_id,
    argMax(function_id, version) AS latest_function_id,
    argMax(parent_run_id, version) AS latest_parent_run_id,
    argMax(kind, version) AS latest_kind,
    argMax(distinct_id, version) AS latest_distinct_id,
    argMax(person_id, version) AS latest_person_id,
    argMax(recipient, version) AS latest_recipient,
    argMax(subject, version) AS latest_subject,
    argMax(status, version) AS latest_status,
    argMax(sent_at, version) AS latest_sent_at,
    argMax(is_deleted, version) AS latest_is_deleted
""".strip()

_OUTER_COLUMNS = """
    invocation_id,
    action_id,
    latest_function_id,
    latest_parent_run_id,
    latest_kind,
    latest_distinct_id,
    latest_person_id,
    latest_recipient,
    latest_subject,
    latest_status,
    latest_sent_at
""".strip()


@dataclasses.dataclass(frozen=True)
class MessageAsset:
    invocation_id: str
    action_id: str
    function_id: str
    parent_run_id: str
    kind: str
    distinct_id: str
    person_id: str
    recipient: str
    subject: str
    status: str
    sent_at: datetime
    # Human-readable workflow name; enriched by the endpoint before serialization.
    # Left blank when the workflow no longer exists so the frontend falls back to function_id.
    function_name: str = ""


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
        help_text="Maximum number of emails to return (1-500, default 50).",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of emails to skip, for pagination.",
    )


def _build_asset(row: tuple) -> MessageAsset:
    return MessageAsset(
        invocation_id=row[0],
        action_id=row[1],
        function_id=row[2],
        parent_run_id=row[3],
        kind=row[4],
        distinct_id=row[5],
        person_id=row[6],
        recipient=row[7],
        subject=row[8],
        status=row[9],
        sent_at=row[10],
    )


def fetch_message_assets(
    team_id: int,
    function_kind: str,
    function_id: str,
    limit: int,
    offset: int = 0,
    parent_run_id: Optional[str] = None,
    action_id: Optional[str] = None,
    invocation_id: Optional[str] = None,
    distinct_id: Optional[str] = None,
    search: Optional[str] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
) -> list[MessageAsset]:
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

    # Filter stable-across-versions fields pre-aggregation to hit the bloom-filter
    # skip indexes. `is_deleted` flips per version, so it's filtered post-collapse.
    if parent_run_id is not None:
        where.append("parent_run_id = %(parent_run_id)s")
        kwargs["parent_run_id"] = parent_run_id
    if action_id:
        where.append("action_id = %(action_id)s")
        kwargs["action_id"] = action_id
    if invocation_id:
        where.append("invocation_id = %(invocation_id)s")
        kwargs["invocation_id"] = invocation_id
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


def fetch_message_assets_for_person(
    team_id: int,
    person_id: str,
    limit: int,
    offset: int = 0,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
) -> list[MessageAsset]:
    where = [
        "team_id = %(team_id)s",
        "person_id = %(person_id)s",
        # Standalone hog_function email destinations aren't surfaced anywhere yet,
        # so this endpoint only returns workflow-step rows.
        "function_kind = 'hog_flow'",
    ]
    kwargs: dict[str, Any] = {
        "team_id": team_id,
        "person_id": person_id,
        "limit": limit,
        "offset": offset,
    }
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


def fetch_message_asset_html(
    team_id: int,
    function_kind: str,
    function_id: str,
    invocation_id: str,
    action_id: str,
) -> Optional[str]:
    kwargs = {
        "team_id": team_id,
        "function_kind": function_kind,
        "function_id": function_id,
        "invocation_id": invocation_id,
        "action_id": action_id,
    }
    # GROUP BY so a no-match query returns zero rows — a bare aggregate would
    # return one default-valued row and the action would serve HTTP 200 + empty.
    query = """
        SELECT latest_html
        FROM (
            SELECT
                argMax(html, version) AS latest_html,
                argMax(is_deleted, version) AS latest_is_deleted
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
    return results[0][0]
