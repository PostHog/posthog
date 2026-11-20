from datetime import timedelta
from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

BASE_URLS = {
    "us": "https://api.appcues.com",
    "eu": "https://api.eu.appcues.com",
}


@frozen
class AppcuesEndpoint:
    path: str
    description: str
    docs_anchor: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "created_at"
    kind: Literal["list", "rules", "event_export", "segment_export"] = "list"
    # The GET that validate_credentials sends, for tables that the sync reads with a POST.
    probe_path: str | None = None
    should_sync_default: bool = True

    @property
    def credential_probe_path(self) -> str:
        return self.probe_path or self.path


# The list endpoints have no documented timestamp filters or pagination.
ENDPOINTS: dict[str, AppcuesEndpoint] = {
    "flows": AppcuesEndpoint(
        path="flows", description="Onboarding flows and their publication settings.", docs_anchor="list-flows"
    ),
    "flows_v2": AppcuesEndpoint(
        path="flows-v2", description="Flows 2.0 and their experience settings.", docs_anchor="list-flows-20"
    ),
    "segments": AppcuesEndpoint(
        path="segments", description="User segments and their creation details.", docs_anchor="list-segments"
    ),
    "tags": AppcuesEndpoint(path="tags", description="Tags used to organize experiences.", docs_anchor="list-tags"),
    "pins": AppcuesEndpoint(
        path="pins", description="Persistent in-app messages and their steps.", docs_anchor="list-pins"
    ),
    "mobile": AppcuesEndpoint(
        path="mobile", description="Mobile experiences and their steps.", docs_anchor="list-mobile-experiences"
    ),
    "launchpads": AppcuesEndpoint(
        path="launchpads", description="Launchpad experiences and their settings.", docs_anchor="list-launchpads"
    ),
    "banners": AppcuesEndpoint(
        path="banners", description="Banner experiences and their settings.", docs_anchor="list-banners"
    ),
    "embeds": AppcuesEndpoint(
        path="embeds", description="Embedded experiences and their settings.", docs_anchor="list-embeds"
    ),
    "nps": AppcuesEndpoint(
        path="nps", description="NPS 2.0 experiences and their settings.", docs_anchor="list-nps-20"
    ),
    "checklists": AppcuesEndpoint(
        path="checklists",
        description="Onboarding checklists and their completion conditions.",
        docs_anchor="list-checklists",
    ),
    "ingestion_filtering_rules": AppcuesEndpoint(
        path="ingestion_filtering_rules",
        description="The account's allow or deny rules for event, profile, and group property names.",
        docs_anchor="get-ingestion-filtering-rules",
        primary_keys=("account_id",),
        partition_key=None,
        kind="rules",
    ),
    "events": AppcuesEndpoint(
        path="export/events",
        description="User events, such as flows seen, completed, and dismissed, from the bulk event export.",
        docs_anchor="export-bulk-event-data",
        primary_keys=(),
        partition_key="timestamp",
        kind="event_export",
        probe_path="jobs",
        should_sync_default=False,
    ),
    "segment_membership": AppcuesEndpoint(
        path="segments",
        description="The users in each segment, from one segment membership export per segment.",
        docs_anchor="export-segment-membership",
        primary_keys=("segment_id", "user_id"),
        partition_key=None,
        kind="segment_export",
        should_sync_default=False,
    ),
}

# The event export filters on a time range. Its rows carry no event id, so the table can only append.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "events": [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

EVENTS_INITIAL_LOOKBACK = timedelta(days=90)
# Appcues caps one export at 10 million events and recommends short ranges, so export one day per job.
EVENTS_EXPORT_WINDOW = timedelta(days=1)
# Leave recent events out of the export until Appcues has ingested them.
EVENTS_EXPORT_END_LAG = timedelta(hours=1)
EXPORT_POLL_INTERVAL_SECONDS = 10
EXPORT_POLL_BUDGET_SECONDS = 30 * 60
EXPORT_BATCH_SIZE = 5000
