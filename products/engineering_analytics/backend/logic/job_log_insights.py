"""Read one GitHub Actions job's log and report what its steps did with caches and migrations.

The job is looked up in the caller's own source on every call, so a reader who cannot read that
source never reaches the log or a cached answer. The log comes from GitHub with the credential of
that same source, never from a walk over the team's other sources (see ``ownership_files``), and
then with the team's GitHub integration that covers the repository.
"""

from dataclasses import asdict, field

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen
from posthog.egress.github.limiter import consume_github_installation_sync
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import CIEngine, JobLogInsights
from products.engineering_analytics.backend.logic.job_logs.badges import parse_job_log
from products.engineering_analytics.backend.logic.job_logs.fetcher import fetch_job_log
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.workflow_jobs import query_workflow_job
from products.warehouse_sources.backend.facade import api as warehouse_sources

logger = structlog.get_logger(__name__)

_EGRESS_SOURCE = "job_logs"
# A person is waiting on the page, so the fetch must not hold the request as long as a worker may.
_FETCH_TIMEOUT_SECONDS = 20
# A completed job's log never changes.
_CACHE_SECONDS = 7 * 24 * 60 * 60
# Part of the cache key. Raise it when the parser's rules or the cached shape change.
_CACHE_VERSION = 1

_LOG_NOT_READ = JobLogInsights(log_read=False, attributed_to_steps=False, job=[], steps=[])


@frozen
class _LogCredential:
    token: str = field(repr=False)
    # None for a personal access token, which draws on the customer's own GitHub budget.
    installation_id: str | None


def build_job_log_insights(
    *, curated: CuratedGitHubSource, run_id: int, job_id: int, ci_engine: CIEngine | None = None
) -> JobLogInsights:
    job = query_workflow_job(curated=curated, run_id=run_id, job_id=job_id, ci_engine=ci_engine)
    if job is None or job.ci_engine is not CIEngine.GITHUB_ACTIONS:
        return _LOG_NOT_READ
    completed = job.status == "completed"
    cache_key = (
        f"engineering_analytics:{curated.team.pk}:job_log_insights:{_CACHE_VERSION}"
        f":{curated.source_id}:{curated.repository.casefold()}:{job_id}"
    )
    if completed:
        cached = _cached(cache_key)
        if cached is not None:
            return cached
    try:
        log_text = _fetch_log(curated.team, curated.repository, curated.source_id, job_id)
    except Exception:
        logger.warning("engineering_analytics_job_log_fetch_failed", job_id=job_id, exc_info=True)
        return _LOG_NOT_READ
    if log_text is None:
        return _LOG_NOT_READ
    insights = parse_job_log(log_text, job.steps)
    if completed:
        try:
            cache.set(cache_key, asdict(insights), timeout=_CACHE_SECONDS)
        except Exception:
            logger.warning("engineering_analytics_cache_write_failed", exc_info=True)
    return insights


def _cached(cache_key: str) -> JobLogInsights | None:
    try:
        value = cache.get(cache_key)
        return JobLogInsights(**value) if isinstance(value, dict) else None
    except Exception:
        logger.warning("engineering_analytics_cache_read_failed", exc_info=True)
        return None


def _fetch_log(team: Team, repository: str, source_id: str, job_id: int) -> str | None:
    credential = _log_credential(team, repository, source_id)
    if credential is None:
        return None
    if credential.installation_id is not None and not consume_github_installation_sync(
        credential.installation_id, priority=Priority.NORMAL, source=_EGRESS_SOURCE
    ):
        return None
    return fetch_job_log(repository, job_id, credential.token, timeout=_FETCH_TIMEOUT_SECONDS)


def _log_credential(team: Team, repository: str, source_id: str) -> _LogCredential | None:
    credential = warehouse_sources.github_source_credential(team_id=team.pk, source_id=source_id) if source_id else None
    if credential is not None and credential.personal_access_token:
        return _LogCredential(token=credential.personal_access_token, installation_id=None)
    github: GitHubIntegration | None = None
    if credential is not None and credential.integration_id is not None:
        integration = Integration.objects.filter(team_id=team.pk, id=credential.integration_id, kind="github").first()
        if integration is not None:
            github = GitHubIntegration(integration, source=_EGRESS_SOURCE, priority=Priority.NORMAL)
    if github is None:
        github = GitHubIntegration.first_for_team_repository(
            team.pk, repository, source=_EGRESS_SOURCE, priority=Priority.NORMAL
        )
    if github is None or not github.github_installation_id:
        return None
    return _LogCredential(token=github.get_access_token(), installation_id=str(github.github_installation_id))
