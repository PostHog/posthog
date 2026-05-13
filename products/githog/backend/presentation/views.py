"""
DRF views for githog.

Exposes a thin read-only API on top of the team's existing GitHub
integration(s) so the GitHog frontend product can list connected
repositories and their pull requests.
"""

from typing import Any

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.integration import GitHubIntegration, Integration

from products.githog.backend.logic.data_flow import compute_data_flow

from .serializers import (
    GitHogDataFlowQuerySerializer,
    GitHogDataFlowResponseSerializer,
    GitHogPullRequestDetailQuerySerializer,
    GitHogPullRequestDetailResponseSerializer,
    GitHogPullRequestListQuerySerializer,
    GitHogPullRequestListResponseSerializer,
    GitHogRepositoryListResponseSerializer,
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
    @action(methods=["GET"], detail=False, url_path="pull_requests")
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

    @extend_schema(
        parameters=[GitHogPullRequestDetailQuerySerializer],
        responses={200: GitHogPullRequestDetailResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="pull_request")
    def pull_request(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = GitHogPullRequestDetailQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        repository: str = query.validated_data["repository"]
        pr_number: int = query.validated_data["number"]

        match = self._find_integration_for_repository(repository)
        if match is None:
            raise NotFound("No GitHub integration on this team has access to that repository")
        integration, _owner, name = match

        result = GitHubIntegration(integration).get_pull_request(name, pr_number)
        if not result.get("success"):
            raise ValidationError(result.get("error") or "Failed to fetch pull request")
        result.pop("success", None)
        return Response(result)

    @extend_schema(
        parameters=[GitHogDataFlowQuerySerializer],
        responses={200: GitHogDataFlowResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="pull_request_data_flow")
    def pull_request_data_flow(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = GitHogDataFlowQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        repository: str = query.validated_data["repository"]
        pr_number: int = query.validated_data["number"]
        refresh: bool = query.validated_data.get("refresh", False)

        match = self._find_integration_for_repository(repository)
        if match is None:
            raise NotFound("No GitHub integration on this team has access to that repository")
        integration, _owner, _name = match

        try:
            row, is_cached = compute_data_flow(
                team=self.team,
                user=request.user,
                integration=integration,
                repository=repository,
                pr_number=pr_number,
                refresh=refresh,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        return Response(
            {
                "repository": row.repository,
                "pr_number": row.pr_number,
                "head_sha": row.head_sha,
                "base_sha": row.base_sha,
                "mermaid_before": row.mermaid_before,
                "mermaid_after": row.mermaid_after,
                "steps_before": row.steps_before,
                "steps_after": row.steps_after,
                "summary": row.summary,
                "truncated": row.truncated,
                "cached": is_cached,
                "computed_at": row.updated_at,
            }
        )
