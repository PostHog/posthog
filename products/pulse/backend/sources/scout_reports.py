from datetime import timedelta

from django.utils import timezone

from posthog.models.team import Team

from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, SourceItem, build_fingerprint_hint
from products.signals.backend.facade.api import get_recent_reports

# Deliberately duplicates the facade's default limit: pulse owns its own prompt budget.
MAX_REPORTS = 20
TITLE_MAX_CHARS = 200
SUMMARY_MAX_CHARS = 1000


class ScoutReportsSource:
    # No availability gate needed: the facade read is already scoped to scout-derived,
    # inbox-visible reports (and returns [] without AI consent), so a team without scouts
    # simply has nothing to gather.
    name = "scout_reports"

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]:
        since = timezone.now() - timedelta(days=period_days)
        items: list[SourceItem] = []
        for report in get_recent_reports(team.id, since=since, limit=MAX_REPORTS):
            title = report.title[:TITLE_MAX_CHARS]
            # Untrusted free text (LLM-authored report prose) is sanitized once at the
            # prompt-render boundary (_render_items)
            items.append(
                SourceItem(
                    source=self.name,
                    kind="signal",
                    title=title,
                    description=report.summary[:SUMMARY_MAX_CHARS],
                    numbers={"weight": report.total_weight, "signal_count": report.signal_count},
                    evidence=[EvidenceRef(type="signal_report", ref=report.id, label=title)],
                    fingerprint_hint=build_fingerprint_hint(self.name, report.id),
                )
            )
        return items
