from datetime import timedelta

from django.utils import timezone

import structlog
import posthoganalytics

from posthog.models.team import Team

from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, SourceItem, build_fingerprint_hint
from products.signals.backend.facade.api import get_recent_reports

logger = structlog.get_logger(__name__)

MAX_REPORTS = 20
TITLE_MAX_CHARS = 200
SUMMARY_MAX_CHARS = 1000

# Team-level gate for the signals scout program. Fine-grained enrollment (a team allowlist in
# the flag payload) lives in signals-internal coordinator code that pulse must not import across
# the product boundary, so this is deliberately the coarse flag check — a team without scouts
# has no inbox reports to gather anyway.
SIGNALS_SCOUT_FLAG = "signals-scout"


class ScoutReportsSource:
    name = "scout_reports"

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]:
        if not self._scouts_available(team):
            return []
        since = timezone.now() - timedelta(days=period_days)
        items: list[SourceItem] = []
        for report in get_recent_reports(team.id, since=since, limit=MAX_REPORTS):
            # Untrusted free text (LLM-authored report prose) is sanitized once at the
            # prompt-render boundary (_render_items)
            items.append(
                SourceItem(
                    source=self.name,
                    kind="signal",
                    title=report.title[:TITLE_MAX_CHARS],
                    description=report.summary[:SUMMARY_MAX_CHARS],
                    numbers={"weight": report.total_weight, "signal_count": report.signal_count},
                    evidence=[EvidenceRef(type="signal_report", ref=report.id, label=report.title[:TITLE_MAX_CHARS])],
                    fingerprint_hint=build_fingerprint_hint(self.name, report.id),
                )
            )
        return items

    def _scouts_available(self, team: Team) -> bool:
        # Fail closed: a flag-service blip must skip this source, not fail the brief gather.
        try:
            return bool(
                posthoganalytics.feature_enabled(
                    SIGNALS_SCOUT_FLAG,
                    str(team.uuid),
                    groups={"organization": str(team.organization_id), "project": str(team.id)},
                    only_evaluate_locally=False,
                    send_feature_flag_events=False,
                )
            )
        except Exception:
            logger.warning("pulse_scout_reports_flag_check_failed", team_id=team.id, exc_info=True)
            return False
