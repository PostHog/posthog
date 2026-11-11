from celery import shared_task

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.models import Team
from posthog.models.scoping import with_team_scope

from products.signals.backend.github_writeback import post_report_link_to_github_issues
from products.signals.backend.signal_metadata import fetch_signals_for_report_sync


@shared_task(ignore_result=True, soft_time_limit=240, time_limit=300)
@with_team_scope()
def post_source_issue_links(team_id: int, report_id: str, signals: list[dict] | None = None) -> None:
    """Comment a link to a report on the GitHub issues it names as its source or that contributed to
    it, or edit that comment after a status change.

    `signals` carries a GitHub issue signal that just joined the report by exact match, which
    ClickHouse may not show yet. Without it, the task reads the report's signals. No retry: the
    writeback swallows per-issue failures, and a later edit, status change, or GitHub signal joining
    the report settles again through the same per-issue claim, which never posts twice.
    """
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return
    if signals is None:
        signals = fetch_signals_for_report_sync(
            team, report_id, ch_user=ClickHouseUser.SIGNALS, workload=Workload.OFFLINE
        )
    post_report_link_to_github_issues(team, report_id, signals=signals)
