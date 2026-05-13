"""
DRF views for githog.

Exposes an API for the GitHog frontend product: connected repositories,
pull requests, and a native per-PR conversation thread.
"""

from typing import Any

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.integration import GitHubIntegration, Integration

from ..models import GitHogConversationMessage
from .serializers import (
    GitHogConversationListQuerySerializer,
    GitHogConversationListResponseSerializer,
    GitHogCreateMessageResponseSerializer,
    GitHogCreateMessageSerializer,
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
        parameters=[GitHogConversationListQuerySerializer],
        responses={200: GitHogConversationListResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="conversations")
    def conversations(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = GitHogConversationListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        repository: str = query.validated_data["repository"]
        number: int = query.validated_data["number"]

        messages = GitHogConversationMessage.objects.filter(
            team_id=self.team_id,
            repository=repository,
            pull_request_number=number,
        ).select_related("author")

        return Response(
            {
                "messages": [
                    {
                        "id": m.id,
                        "author_name": m.author.get_full_name() or m.author.email if m.author else "Unknown",
                        "author_email": m.author.email if m.author else "",
                        "body": m.body,
                        "created_at": m.created_at,
                    }
                    for m in messages
                ]
            }
        )

    @extend_schema(
        request=GitHogCreateMessageSerializer,
        responses={201: GitHogCreateMessageResponseSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="conversations/create")
    def create_conversation_message(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body_ser = GitHogCreateMessageSerializer(data=request.data)
        body_ser.is_valid(raise_exception=True)
        repository: str = body_ser.validated_data["repository"]
        number: int = body_ser.validated_data["number"]
        body: str = body_ser.validated_data["body"]

        message = GitHogConversationMessage.objects.create(
            team_id=self.team_id,
            repository=repository,
            pull_request_number=number,
            author=request.user,
            body=body,
        )

        return Response(
            {
                "message": {
                    "id": message.id,
                    "author_name": message.author.get_full_name() or message.author.email if message.author else "",
                    "author_email": message.author.email if message.author else "",
                    "body": message.body,
                    "created_at": message.created_at,
                }
            },
            status=status.HTTP_201_CREATED,
        )
