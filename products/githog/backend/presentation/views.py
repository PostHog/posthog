"""
DRF views for githog.

Two viewsets:

- ``GitHogViewSet`` — read-only access to the team's GitHub integration(s):
  list connected repositories and their pull requests. Used by the GitHog
  frontend to populate repo/PR pickers.

- ``GithogPRImpactViewSet`` — user-impact analysis for a PR diff. Extracts
  feature-flag keys from the supplied diff and measures empirical reach
  from ``$feature_flag_called`` events. Avoids HTTP-layer business logic;
  delegates to ``facade/api.py``.
"""

from typing import Any

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action as rf_action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import extend_schema as posthog_extend_schema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.integration import GitHubIntegration, Integration

from ..facade.api import compute_pr_impact
from ..facade.contracts import PRImpactRequest
from .serializers import (
    GitHogPullRequestListQuerySerializer,
    GitHogPullRequestListResponseSerializer,
    GitHogRepositoryListResponseSerializer,
    PRImpactRequestSerializer,
    PRImpactResponseSerializer,
)

logger = structlog.get_logger(__name__)


class GitHogViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read-only views over the team's GitHub integration(s) for the GitHog product."""

    scope_object = "integration"

    def _team_github_integrations(self) -> list[Integration]:
        return list(Integration.objects.filter(team_id=self.team_id, kind="github").order_by("id"))

    def _find_integration_for_repository(self, repository: str) -> tuple[Integration, str, str] | None:
        """Return (integration, owner, name) for the first team GitHub integration whose
        cached repository list contains ``repository`` (``owner/name``)."""
        if "/" not in repository:
            return None
        owner, name = repository.split("/", 1)
        for integration in self._team_github_integrations():
            github = GitHubIntegration(integration)
            try:
                cached = github.list_all_cached_repositories()
            except Exception:
                logger.warning(
                    "githog: failed to load cached repositories",
                    integration_id=integration.id,
                    exc_info=True,
                )
                continue
            if any(str(repo.get("full_name", "")).casefold() == repository.casefold() for repo in cached):
                return integration, owner, name
        return None

    @extend_schema(responses={200: GitHogRepositoryListResponseSerializer})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        repositories: list[dict[str, Any]] = []
        seen_full_names: set[str] = set()
        for integration in self._team_github_integrations():
            github = GitHubIntegration(integration)
            try:
                cached = github.list_all_cached_repositories()
            except Exception:
                logger.warning(
                    "githog: failed to load cached repositories",
                    integration_id=integration.id,
                    exc_info=True,
                )
                continue
            for repo in cached:
                full_name = str(repo.get("full_name", ""))
                if not full_name or full_name in seen_full_names:
                    continue
                seen_full_names.add(full_name)
                owner, _, name = full_name.partition("/")
                repositories.append(
                    {
                        "id": repo.get("id"),
                        "name": repo.get("name") or name,
                        "full_name": full_name,
                        "owner": owner,
                        "integration_id": integration.id,
                    }
                )

        repositories.sort(key=lambda r: r["full_name"].casefold())
        return Response({"repositories": repositories})

    @extend_schema(
        parameters=[GitHogPullRequestListQuerySerializer],
        responses={200: GitHogPullRequestListResponseSerializer},
    )
    @rf_action(methods=["GET"], detail=False, url_path="pull_requests")
    def pull_requests(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = GitHogPullRequestListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        repository: str = query.validated_data["repository"]
        state: str = query.validated_data.get("state", "open")

        match = self._find_integration_for_repository(repository)
        if match is None:
            raise NotFound("No GitHub integration on this team has access to that repository")

        integration, _owner, name = match
        github = GitHubIntegration(integration)
        result = github.list_pull_requests(name, state=state)
        if not result.get("success"):
            raise ValidationError(result.get("error") or "Failed to list pull requests")

        return Response(
            {
                "repository": repository,
                "pull_requests": result.get("pull_requests", []),
            }
        )


@posthog_extend_schema(tags=["githog"])
class GithogPRImpactViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """User-impact analysis for pull request diffs."""

    scope_object = "INTERNAL"

    @validated_request(
        request_serializer=PRImpactRequestSerializer,
        responses={200: OpenApiResponse(response=PRImpactResponseSerializer)},
        operation_id="githog_pr_impact_create",
        summary="Compute user-impact for a PR diff",
        description=(
            "Extracts PostHog feature-flag keys referenced in the supplied unified diff, "
            "then queries `$feature_flag_called` events to report how many users hit each "
            "flag (and the intersection across all flags) over the lookback window. "
            "Empirical — does not multiply configured rollout percentages, so it handles "
            "compounding nested gates correctly."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="pr_impact")
    def pr_impact(self, request: ValidatedRequest, **kwargs: object) -> Response:
        params = dict(request.validated_data)
        impact_request = PRImpactRequest(
            diff_text=params["diff_text"],
            lookback_days=params.get("lookback_days", 30),
        )
        report = compute_pr_impact(self.team, impact_request)
        return Response(PRImpactResponseSerializer.from_report(report))
