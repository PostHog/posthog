import re
from datetime import timedelta

from django.utils import timezone

from products.warehouse_sources.backend.facade.api import list_failing_sources
from products.warehouse_sources.backend.facade.contracts import FailingSource

from ...facade.enums import HighlightLabel
from ..highlight_rules import short
from ..highlight_types import Candidate, Context, Found, Source

FAILED_SYNC = "{source} sync failed {times} in the last 7 days"
FAILED_SYNC_NAMED = "{source} sync ‘{label}’ failed {times} in the last 7 days"
FAILED_SYNC_DETAIL = "Last error: {error}"
IDS = re.compile(r"\s*(for|in) \w+ \d{5,}|\b\d{5,}\b")
RETRY_NOTE = re.compile(r";?\s*deferring.*$")


def find(context: Context) -> Found:
    sources = list_failing_sources(context.team.id, context.user.id, since=timezone.now() - timedelta(days=7), limit=3)
    return Found(items=tuple(_candidate(source) for source in sources))


def _candidate(source: FailingSource) -> Candidate:
    error = RETRY_NOTE.sub("", IDS.sub("", source.latest_error or "")).rstrip("; .")
    return Candidate(
        key=f"failed_sync:{source.source_id}",
        label=HighlightLabel.RISK,
        family="pipelines",
        importance=0.75,
        relevance=1.0,
        title=(FAILED_SYNC_NAMED if source.source_label else FAILED_SYNC).format(
            source=source.source_type,
            label=short(source.source_label or "", 40),
            times="once" if source.failures == 1 else f"{source.failures} times",
        ),
        detail=FAILED_SYNC_DETAIL.format(error=short(error, 80) or "unknown"),
        url=f"/data-warehouse/sources/{source.source_id}",
    )


SOURCE = Source(name="warehouse_syncs", find=find, scopes=("external_data_source:read",))
