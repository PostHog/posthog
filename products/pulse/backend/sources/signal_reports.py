from datetime import timedelta

from django.utils import timezone

from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControl

from products.pulse.backend.config import (
    SIGNAL_REPORT_SUMMARY_MAX_CHARS,
    SIGNAL_REPORT_TITLE_MAX_CHARS,
    SIGNAL_REPORTS_MAX,
)
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, SourceItemKind
from products.pulse.backend.urls import inbox_report_url
from products.signals.backend.facade.api import get_recent_reports


def _truncate(text: str, limit: int) -> str:
    # Bounds each SourceItem under the Temporal payload limit; the ellipsis marks the brief as
    # seeing an excerpt, not the full report.
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class SignalReportsSource:
    """Recent signals-inbox reports (scout and replay-vision findings) surfaced as signal items —
    pre-analyzed detections the LLM weighs as evidence when forming the narrative.

    No availability gate needed: the facade read is already scoped to inbox-visible reports (and
    returns [] without AI consent), so a team with no reports simply has nothing to gather.
    """

    name = "signal_reports"

    def gather(
        self, team: Team, config: BriefConfig | None, lookback_days: int, user_access_control: UserAccessControl
    ) -> list[SourceItem]:
        since = timezone.now() - timedelta(days=lookback_days)
        items: list[SourceItem] = []
        for report in get_recent_reports(team.id, since=since, limit=SIGNAL_REPORTS_MAX):
            title = _truncate(report.title, SIGNAL_REPORT_TITLE_MAX_CHARS)
            # Report prose is LLM-authored; it is additionally sanitized for prompt injection at
            # the render boundary (_render_items).
            items.append(
                SourceItem(
                    source=self.name,
                    kind=SourceItemKind.SIGNAL,
                    title=title,
                    description=_truncate(report.summary, SIGNAL_REPORT_SUMMARY_MAX_CHARS),
                    metrics={"weight": report.total_weight, "signal_count": report.signal_count},
                    evidence=[
                        EvidenceRef(
                            type=EvidenceType.SIGNAL_REPORT,
                            ref=str(report.id),
                            label=title,
                            url=inbox_report_url(team.id, str(report.id)),
                        )
                    ],
                    fingerprint_hint=f"signal_report:{report.id}",
                )
            )
        return items
