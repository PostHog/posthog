"""
DRF views for visual_review.

Responsibilities:
- Validate incoming JSON (via serializers)
- Convert JSON to DTOs
- Call facade methods (api/api.py)
- Convert DTOs to JSON responses

No business logic here - that belongs in logic.py via the facade.
"""

from typing import cast
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api
from ..facade.contracts import (
    ApproveRunInput,
    ApproveRunRequestInput,
    CreateRepoInput,
    CreateRunInput,
    UpdateRepoInput,
    UpdateRepoRequestInput,
)
from .serializers import (
    ApproveRunInputSerializer,
    CreateRepoInputSerializer,
    CreateRunInputSerializer,
    CreateRunResultSerializer,
    RepoSerializer,
    RunSerializer,
    SnapshotSerializer,
    UpdateRepoInputSerializer,
)

# TODO: Add VISUAL_REVIEW to frontend/src/queries/schema/schema-general.ts ProductKey enum
# and regenerate posthog/schema.py, then use ProductKey.VISUAL_REVIEW here
VISUAL_REVIEW_TAG = "visual_review"


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class RepoViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Projects for visual review.

    A repo typically represents a repository or test suite.
    """

    # TODO: Add "visual_review" to APIScopeObject in posthog/scopes.py
    scope_object = "repo"
    scope_object_write_actions = ["create", "partial_update"]
    scope_object_read_actions = ["list", "retrieve"]

    @extend_schema(responses={200: RepoSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List all projects for the team."""
        projects = api.list_repos(self.team_id)
        return Response(RepoSerializer(instance=projects, many=True).data)

    @validated_request(
        request_serializer=CreateRepoInputSerializer,
        responses={201: OpenApiResponse(response=RepoSerializer)},
    )
    def create(self, request: ValidatedRequest[CreateRepoInput], **kwargs) -> Response:
        """Create a new repo."""
        repo = api.create_repo(team_id=self.team_id, name=request.validated_data.name)
        return Response(RepoSerializer(instance=repo).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: RepoSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Get a repo by ID."""
        try:
            repo = api.get_repo(UUID(pk))
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RepoSerializer(instance=repo).data)

    @validated_request(
        request_serializer=UpdateRepoInputSerializer,
        responses={200: OpenApiResponse(response=RepoSerializer)},
    )
    def partial_update(self, request: ValidatedRequest[UpdateRepoRequestInput], pk: str, **kwargs) -> Response:
        """Update a repo's settings."""
        body = request.validated_data
        input_dto = UpdateRepoInput(
            repo_id=UUID(pk),
            name=body.name,
            repo_full_name=body.repo_full_name,
            baseline_file_paths=body.baseline_file_paths,
        )

        try:
            repo = api.update_repo(input_dto)
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RepoSerializer(instance=repo).data)


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class RunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Visual review runs.

    A run represents a single CI execution that captures screenshots.
    """

    # TODO: Add "visual_review" to APIScopeObject in posthog/scopes.py
    scope_object = "repo"
    scope_object_write_actions = ["create", "complete", "approve"]
    scope_object_read_actions = ["list", "retrieve", "snapshots"]

    @extend_schema(responses={200: RunSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List all runs for the team."""
        runs = api.list_runs(self.team_id)
        page = self.paginate_queryset(runs)
        if page is not None:
            serializer = RunSerializer(instance=page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(RunSerializer(instance=runs, many=True).data)

    @validated_request(
        request_serializer=CreateRunInputSerializer,
        responses={201: OpenApiResponse(response=CreateRunResultSerializer)},
    )
    def create(self, request: ValidatedRequest[CreateRunInput], **kwargs) -> Response:
        """Create a new run from a CI manifest."""
        result = api.create_run(request.validated_data)
        return Response(CreateRunResultSerializer(instance=result).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: RunSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Get run status and summary."""
        try:
            run = api.get_run(UUID(pk))
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RunSerializer(instance=run).data)

    @extend_schema(responses={200: SnapshotSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def snapshots(self, request: Request, pk: str, **kwargs) -> Response:
        """Get all snapshots for a run with diff results."""
        try:
            snapshots = api.get_run_snapshots(UUID(pk))
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        page = self.paginate_queryset(snapshots)
        if page is not None:
            serializer = SnapshotSerializer(instance=page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(SnapshotSerializer(instance=snapshots, many=True).data)

    @extend_schema(responses={200: RunSerializer})
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str, **kwargs) -> Response:
        """Signal that all artifacts have been uploaded. Triggers diff processing."""
        try:
            run = api.complete_run(UUID(pk))
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RunSerializer(instance=run).data)

    @validated_request(
        request_serializer=ApproveRunInputSerializer,
        responses={200: OpenApiResponse(response=RunSerializer)},
    )
    @action(detail=True, methods=["post"])
    def approve(self, request: ValidatedRequest[ApproveRunRequestInput], pk: str, **kwargs) -> Response:
        """Approve visual changes for snapshots in this run."""
        body = request.validated_data
        input_dto = ApproveRunInput(
            run_id=UUID(pk),
            user_id=cast(int, request.user.id),
            snapshots=body.snapshots,
            commit_to_github=body.commit_to_github,
        )

        try:
            run = api.approve_run(input_dto)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        except api.ArtifactNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except api.GitHubIntegrationNotFoundError:
            return Response(
                {"detail": "No GitHub integration configured. Please install the GitHub App for this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except api.PRSHAMismatchError as e:
            return Response(
                {"detail": str(e), "code": "sha_mismatch"},
                status=status.HTTP_409_CONFLICT,
            )
        except api.GitHubCommitError as e:
            return Response(
                {"detail": f"GitHub commit failed: {e}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except api.BaselineFilePathNotConfiguredError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(RunSerializer(instance=run).data)
