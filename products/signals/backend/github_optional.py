from __future__ import annotations

from django.db.models import Q

import structlog
import posthoganalytics
from requests import RequestException
from rest_framework.exceptions import APIException

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.integrations import IntegrationManager
from posthog.models.github_integration_base import _is_safe_github_repo_path
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError
from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.models import SignalTeamConfig

logger = structlog.get_logger(__name__)

GITHUB_OPTIONAL_FLAG = "self-driving-github-optional"
GITHUB_OPTIONAL_ACTIVATION = "github_optional"


class RepositoryAccessTemporarilyUnavailable(APIException):
    status_code = 503
    default_code = "github_access_temporarily_unavailable"
    default_detail = "GitHub access could not be checked. Try again shortly."

    def __init__(self, *, wait: int | None = None) -> None:
        super().__init__()
        self.wait = wait


class ResearchAccessPolicy:
    @staticmethod
    def repository_integration_id(team_id: int, repository: str, *, priority: Priority = Priority.NORMAL) -> int | None:
        if not _is_safe_github_repo_path(repository):
            return None
        transient_error: Exception | None = None
        for integration in IntegrationManager.github.oauth.list(team_id):
            try:
                github = GitHubIntegration(integration, source="signals_github_optional", priority=priority)
                if github.installation_can_access_repository(repository, raise_on_transient=True):
                    return integration.id
            except GitHubIntegrationError as error:
                if error.status_code is None or error.status_code >= 500:
                    transient_error = error
            except (GitHubRateLimitError, EgressBudgetExhausted, RequestException) as error:
                transient_error = error
        if transient_error is not None:
            raise RepositoryAccessTemporarilyUnavailable(
                wait=transient_error.retry_after if isinstance(transient_error, GitHubRateLimitError) else None
            ) from transient_error
        return None

    @staticmethod
    def repository_available(team_id: int, repository: str, *, priority: Priority = Priority.NORMAL) -> bool:
        return ResearchAccessPolicy.repository_integration_id(team_id, repository, priority=priority) is not None

    @staticmethod
    def enabled_for_project(project: Team, *, only_evaluate_locally: bool = False) -> bool:
        try:
            return (
                feature_enabled_or_false(
                    GITHUB_OPTIONAL_FLAG,
                    str(project.uuid),
                    groups={"project": str(project.uuid)},
                    group_properties={"project": {"id": project.id, "uuid": str(project.uuid)}},
                    send_feature_flag_events=False,
                    only_evaluate_locally=only_evaluate_locally,
                )
                is True
            )
        except Exception:
            logger.warning("github_optional_pilot_flag_failed", team_id=project.id, exc_info=True)
            return False

    @staticmethod
    def enabled(team_id: int) -> bool:
        team = Team.objects.select_related("parent_team").get(id=team_id)
        return ResearchAccessPolicy.enabled_for_project(team.parent_team or team)

    @staticmethod
    def enrolled(team_id: int) -> bool:
        return SignalTeamConfig.objects.filter(
            Q(team_id=team_id) | Q(team__parent_team_id=team_id),
            onboarding__draft__activation_mode=GITHUB_OPTIONAL_ACTIVATION,
            onboarding__completed_at__isnull=False,
        ).exclude(onboarding__completed_at=None).exists() and ResearchAccessPolicy.enabled(team_id)

    @staticmethod
    def enrolled_team_ids(*, exclude_team_ids: set[int] | None = None) -> set[int]:
        # Even local-only evaluation loads definitions synchronously when the SDK is cold.
        client = posthoganalytics.default_client
        if client is None or client.feature_flags is None:
            return set()
        projects = {
            parent_id or team_id
            for team_id, parent_id in SignalTeamConfig.objects.filter(
                onboarding__draft__activation_mode=GITHUB_OPTIONAL_ACTIVATION,
                onboarding__completed_at__isnull=False,
            )
            .exclude(onboarding__completed_at=None)
            .values_list("team_id", "team__parent_team_id")
        }
        projects -= exclude_team_ids or set()
        return {
            project.id
            for project in Team.objects.filter(id__in=projects).only("id", "uuid")
            if ResearchAccessPolicy.enabled_for_project(project, only_evaluate_locally=True)
        }


def team_has_code_access(team_id: int) -> bool:
    """Whether Self-driving can read this team's code.

    False is what "running Self-driving without GitHub" means: no installation, none that still
    reaches a repository, or none healthy enough to use. This is the branch that decides whether
    report research runs in `code` or `data_only` mode, so a caller that gates on code access must
    use it rather than test for an installation itself. Answered from Postgres alone, so a caller
    on a per-report path can afford it.
    """
    # The repo-selection agent is not importable at django.setup().
    from products.tasks.backend.facade.repo_selection import resolve_team_github_integration  # noqa: PLC0415

    # `team_only` because the personal and org-owner fallbacks would make a team that never
    # connected GitHub itself look connected.
    return resolve_team_github_integration(team_id, team_only=True) is not None
