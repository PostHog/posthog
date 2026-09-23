"""Celery tasks for engineering_analytics."""

import structlog
from celery import shared_task

from posthog.egress.limiter.policies import Priority
from posthog.models.integration.github import GitHubIntegration
from posthog.models.scoping import with_team_scope
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit

from products.engineering_analytics.backend.logic.census import collect_repo_census, emit_census_events
from products.engineering_analytics.backend.logic.sources import list_github_sources
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
# Fan-out across every team with a GitHub source: cross-team by design, and the model still
# uses a plain manager, so there is no unscoped() to declare it with.
@skip_team_scope_audit
def emit_test_ownership_census() -> None:
    team_ids = (
        ExternalDataSource.objects.filter(source_type=ExternalDataSourceType.GITHUB, deleted=False)
        .values_list("team_id", flat=True)
        .distinct()
    )
    for team_id in team_ids:
        emit_team_test_census.delay(team_id=team_id)


@shared_task(ignore_result=True)
@with_team_scope()
def emit_team_test_census(team_id: int) -> None:
    team = Team.objects.get(id=team_id)
    seen_repos: set[str] = set()
    for source in list_github_sources(team=team, user_access_control=None):
        # Unsynced sources have no resolvable repository for the roster query, so their
        # events would be unreadable; two sources on one repo would double the tarball fetch.
        if not source.repo or not source.synced or source.repo in seen_repos:
            continue
        seen_repos.add(source.repo)
        integration = GitHubIntegration.first_for_team_repository(
            team.id, source.repo, source="owners_census", priority=Priority.BATCH
        )
        token = integration.installation_access_token if integration else None
        if not token:
            logger.info("owners_census_skipped_no_integration", team_id=team_id, repository=source.repo)
            continue
        rows = collect_repo_census(source.repo, token)
        emit_census_events(team, source.repo, rows)
