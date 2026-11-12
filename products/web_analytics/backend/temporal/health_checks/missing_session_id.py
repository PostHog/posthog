import datetime as dt

from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.framework import (
    _SEVERITY_WEIGHT,
    AlertContent,
    Remediation,
    SignalContent,
    build_signal_extra,
)
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.rollups.checks import RollupHealthCheck
from posthog.temporal.health_checks.rollups.freshness import RollupWindow

from products.web_analytics.backend.models.health_rollups import EventsHealthDaily
from products.web_analytics.backend.temporal.health_checks.rollup_reads import events_health_totals

MISSING_SESSION_ID_LOOKBACK_DAYS = 30

# The recent window decides when the issue clears. The 30-day share is stable enough to detect a
# problem, but it keeps matching for almost a month after a fix, because the old events stay in the
# window. A team must also fail the recent window to stay flagged, so a fix clears the issue about a
# week later instead.
MISSING_SESSION_ID_RECENT_DAYS = 7

# A healthy project sits near zero, so the share threshold is far above the noise floor. The volume
# floor counts unusable pageviews rather than total pageviews: a floor on the total suppresses a
# low-traffic project whose every pageview is unusable, which is the case this check exists to find.
MISSING_SESSION_ID_THRESHOLD = 0.05
MISSING_SESSION_ID_MIN_UNUSABLE = 100


class MissingSessionIdCheck(RollupHealthCheck):
    name = "missing_session_id"
    kind = "missing_session_id"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    product = Product.WEB_ANALYTICS
    schedule = "0 6 * * *"
    active_since_days = 30
    rollup_model = EventsHealthDaily
    window_days = MISSING_SESSION_ID_LOOKBACK_DAYS
    remediation = Remediation(
        human=f"""
            Open the Web analytics health page. Web analytics builds sessions only from a UUIDv7
            $session_id, and leaves out every $pageview whose $session_id is absent, is not a UUID, or is
            another UUID version. Those events undercount your visitor and session counts. This usually
            comes from events sent server-side or through a third-party pipeline. Attach a UUIDv7
            $session_id to those events. A plain UUIDv4 is not enough. The check also reads the last
            {MISSING_SESSION_ID_RECENT_DAYS} days, so the warning clears about a week after the fix. See
            https://posthog.com/docs/data/sessions#custom-session-ids.
        """,
        agent=f"""
            Use `execute-sql` to size the gap: over the last {MISSING_SESSION_ID_RECENT_DAYS} days, count
            $pageview events and split them by whether properties.$session_id parses as a UUID
            (toUUIDOrNull) and whether its version nibble is 7
            (bitAnd(bitShiftRight(toUInt128(toUUIDOrNull(properties.$session_id)), 76), 0xF) = 7). Then fix
            it in the user's codebase: find where $pageview events are produced outside posthog-js, such as
            server-side SDK calls or a third-party pipeline, and set a UUIDv7 $session_id on each event. A
            plain UUIDv4, which crypto.randomUUID() and uuid.uuid4() produce, does not work: web analytics
            builds sessions only from UUIDv7 ids, so a UUIDv4 leaves the counts low. Use `docs-search` for
            the custom session id docs. The check needs the last {MISSING_SESSION_ID_RECENT_DAYS} days to
            look clean, so the warning clears about a week after the fix rather than on the next check run.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="Pageviews missing a usable session id",
            summary=issue.payload.get("reason", "$pageview events arrive without a usable $session_id"),
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "Pageviews missing a usable session id"
        summary = issue.payload.get("reason", "$pageview events arrive without a usable $session_id.")
        return SignalContent(
            description=(
                f"A meaningful share of this project's `$pageview` events arrive without a `$session_id` that "
                f"web analytics can use, over the last {MISSING_SESSION_ID_LOOKBACK_DAYS} days. Web analytics "
                "builds sessions only from UUIDv7 ids, and excludes every event whose `$session_id` is absent, "
                "is not a UUID, or is another UUID version, so visitor and session counts come in under the real "
                "numbers while the raw events stay queryable in product analytics. This usually means events are "
                "sent server-side or through a third-party pipeline. Recommend attaching a UUIDv7 `$session_id` "
                "to those events, since a plain UUIDv4 will not restore the counts."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

    def detect_from_rollup(self, team_ids: list[int], window: RollupWindow) -> dict[int, list[HealthCheckResult]]:
        candidates = {
            team_id: totals
            for team_id, totals in events_health_totals(team_ids, window).items()
            if totals.pageviews_unusable_session_id >= MISSING_SESSION_ID_MIN_UNUSABLE
            and _over_threshold(totals.pageviews_unusable_session_id, totals.pageviews)
        }
        if not candidates:
            return {}
        recent_start = max(window.start, window.end - dt.timedelta(days=MISSING_SESSION_ID_RECENT_DAYS - 1))
        recent = events_health_totals(list(candidates), RollupWindow(start=recent_start, end=window.end))
        return {
            team_id: [
                _missing_session_id_result(
                    total_pageviews=totals.pageviews,
                    unusable_pageviews=totals.pageviews_unusable_session_id,
                    absent_or_not_uuid=totals.pageviews_absent_session_id,
                )
            ]
            for team_id, totals in candidates.items()
            if _over_threshold(recent[team_id].pageviews_unusable_session_id, recent[team_id].pageviews)
        }


def _over_threshold(unusable_pageviews: int, total_pageviews: int) -> bool:
    return unusable_pageviews >= total_pageviews * MISSING_SESSION_ID_THRESHOLD


def _missing_session_id_result(
    *, total_pageviews: int, unusable_pageviews: int, absent_or_not_uuid: int
) -> HealthCheckResult:
    share = unusable_pageviews / total_pageviews
    wrong_uuid_version = unusable_pageviews - absent_or_not_uuid
    return HealthCheckResult(
        severity=HealthIssue.Severity.WARNING,
        payload={
            "reason": (
                f"{share:.1%} of $pageview events ({unusable_pageviews} of {total_pageviews}) "
                f"carried a $session_id web analytics cannot use in last "
                f"{MISSING_SESSION_ID_LOOKBACK_DAYS} days "
                f"({absent_or_not_uuid} absent or not a UUID, {wrong_uuid_version} not a UUIDv7)"
            )
        },
        hash_keys=[],
    )
