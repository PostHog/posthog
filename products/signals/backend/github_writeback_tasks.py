from celery import shared_task

from posthog.models import Team
from posthog.models.scoping import with_team_scope

from products.signals.backend.github_writeback import post_report_link_to_github_issues


@shared_task(ignore_result=True, soft_time_limit=240, time_limit=300)
@with_team_scope()
def post_source_issue_links(team_id: int, report_id: str, signals: list[dict] | None = None) -> None:
    """Comment a link to a scout-authored report on the GitHub issues it names as its source.

    `signals` carries a GitHub issue signal that just joined the report by exact match, which
    ClickHouse may not show yet. No retry: the writeback swallows per-issue failures, and a later
    edit or a GitHub signal joining the report settles again through the same per-issue claim,
    which never posts twice.
    """
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return
    post_report_link_to_github_issues(team, report_id, signals=signals or [])
