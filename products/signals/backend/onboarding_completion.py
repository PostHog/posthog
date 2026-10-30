from __future__ import annotations

from requests import RequestException
from rest_framework.exceptions import APIException

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.integrations import IntegrationManager
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalSourceConfig


class RepositoryCheckUnavailable(APIException):
    status_code = 503
    default_detail = "Could not verify GitHub access. Please retry activation shortly."
    default_code = "repository_check_unavailable"


class InboxOnboardingReconciler:
    def __init__(self, team_id: int) -> None:
        self.team_id = team_id

    @staticmethod
    def scouts_can_emit(team_id: int) -> bool:
        return SignalSourceConfig.is_source_enabled(
            team_id, SignalSourceConfig.SourceProduct.SIGNALS_SCOUT, SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE
        )

    def has_repository(self) -> bool:
        failure: Exception | None = None
        for integration in sorted(IntegrationManager.github.oauth.list(self.team_id), key=lambda row: row.id):
            github = GitHubIntegration(integration, source="signals_onboarding", priority=Priority.NORMAL)
            try:
                repositories, _ = github.list_repositories(per_page=1)
            except (GitHubIntegrationError, GitHubRateLimitError, EgressBudgetExhausted, RequestException) as error:
                failure = failure or error
                continue
            if repositories:
                return True
        if failure is not None:
            raise RepositoryCheckUnavailable() from failure
        return False
