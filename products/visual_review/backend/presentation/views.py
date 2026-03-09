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

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
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
    AutoApproveResultSerializer,
    CreateRepoInputSerializer,
    CreateRunInputSerializer,
    CreateRunResultSerializer,
    RepoSerializer,
    ReviewStateCountsSerializer,
    RunSerializer,
    SnapshotHistoryEntrySerializer,
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

    scope_object = "visual_review"
    scope_object_write_actions = ["create", "partial_update"]
    scope_object_read_actions = ["list", "retrieve"]

    @extend_schema(responses={200: RepoSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List all projects for the team."""
        projects = api.list_repos(self.team_id)
        page = self.paginate_queryset(projects)
        if page is not None:
            serializer = RepoSerializer(instance=page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(RepoSerializer(instance=projects, many=True).data)

    @validated_request(
        request_serializer=CreateRepoInputSerializer,
        responses={201: OpenApiResponse(response=RepoSerializer)},
    )
    def create(self, request: TypedRequest[CreateRepoInput], **kwargs) -> Response:
        """Create a new repo."""
        data = request.validated_data
        if data.repo_external_id is None:
            return Response({"detail": "repo_external_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        repo = api.create_repo(
            team_id=self.team_id,
            repo_external_id=data.repo_external_id,
            repo_full_name=data.repo_full_name,
        )
        return Response(RepoSerializer(instance=repo).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: RepoSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Get a repo by ID."""
        try:
            repo = api.get_repo(UUID(pk), team_id=self.team_id)
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RepoSerializer(instance=repo).data)

    @validated_request(
        request_serializer=UpdateRepoInputSerializer,
        responses={200: OpenApiResponse(response=RepoSerializer)},
    )
    def partial_update(self, request: TypedRequest[UpdateRepoRequestInput], pk: str, **kwargs) -> Response:
        """Update a repo's settings."""
        body = request.validated_data
        input_dto = UpdateRepoInput(
            repo_id=UUID(pk),
            baseline_file_paths=body.baseline_file_paths,
        )

        try:
            repo = api.update_repo(input_dto, team_id=self.team_id)
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RepoSerializer(instance=repo).data)


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class RunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Visual review runs.

    A run represents a single CI execution that captures screenshots.
    """

    scope_object = "visual_review"
    scope_object_write_actions = ["create", "complete", "approve", "auto_approve"]
    scope_object_read_actions = ["list", "retrieve", "snapshots", "counts"]

    @extend_schema(
        parameters=[OpenApiParameter("review_state", str, required=False, description="Filter by review state")],
        responses={200: RunSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        """List runs for the team, optionally filtered by review state."""
        review_state = request.query_params.get("review_state")
        runs = api.list_runs(self.team_id, review_state=review_state)
        page = self.paginate_queryset(runs)
        if page is not None:
            serializer = RunSerializer(instance=page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(RunSerializer(instance=runs, many=True).data)

    @extend_schema(responses={200: ReviewStateCountsSerializer})
    @action(detail=False, methods=["get"])
    def counts(self, request: Request, **kwargs) -> Response:
        """Review state counts for the runs list."""
        return Response(api.get_review_state_counts(self.team_id))

    @validated_request(
        request_serializer=CreateRunInputSerializer,
        responses={201: OpenApiResponse(response=CreateRunResultSerializer)},
    )
    def create(self, request: TypedRequest[CreateRunInput], **kwargs) -> Response:
        """Create a new run from a CI manifest."""
        result = api.create_run(request.validated_data, team_id=self.team_id)
        return Response(CreateRunResultSerializer(instance=result).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: RunSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Get run status and summary."""
        try:
            run = api.get_run(UUID(pk), team_id=self.team_id)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RunSerializer(instance=run).data)

    @extend_schema(responses={200: SnapshotSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def snapshots(self, request: Request, pk: str, **kwargs) -> Response:
        """Get all snapshots for a run with diff results."""
        try:
            snapshots = api.get_run_snapshots(UUID(pk), team_id=self.team_id)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        page = self.paginate_queryset(snapshots)
        if page is not None:
            serializer = SnapshotSerializer(instance=page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(SnapshotSerializer(instance=snapshots, many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("identifier", str, required=True, description="Snapshot identifier")],
        responses={200: SnapshotHistoryEntrySerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="snapshot-history")
    def snapshot_history(self, request: Request, pk: str, **kwargs) -> Response:
        """Recent change history for a snapshot identifier across runs."""
        identifier = request.query_params.get("identifier")
        if not identifier:
            return Response({"detail": "identifier query param required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            run = api.get_run(UUID(pk), team_id=self.team_id)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)

        history = api.get_snapshot_history(run.repo_id, identifier)
        return Response(SnapshotHistoryEntrySerializer(instance=history, many=True).data)

    @extend_schema(responses={200: RunSerializer})
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str, **kwargs) -> Response:
        """Signal that all artifacts have been uploaded. Triggers diff processing."""
        try:
            run = api.complete_run(UUID(pk), team_id=self.team_id)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RunSerializer(instance=run).data)

    @validated_request(
        request_serializer=ApproveRunInputSerializer,
        responses={200: OpenApiResponse(response=RunSerializer)},
    )
    @action(detail=True, methods=["post"])
    def approve(self, request: TypedRequest[ApproveRunRequestInput], pk: str, **kwargs) -> Response:
        """Approve visual changes for snapshots in this run."""
        body = request.validated_data
        input_dto = ApproveRunInput(
            run_id=UUID(pk),
            user_id=cast(int, request.user.id),
            snapshots=body.snapshots,
            commit_to_github=body.commit_to_github,
        )

        try:
            run = api.approve_run(input_dto, team_id=self.team_id)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        except api.StaleRunError as e:
            return Response(
                {"detail": str(e), "code": "stale_run"},
                status=status.HTTP_409_CONFLICT,
            )
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

    @extend_schema(responses={200: AutoApproveResultSerializer})
    @action(detail=True, methods=["post"], url_path="auto-approve")
    def auto_approve(self, request: Request, pk: str, **kwargs) -> Response:
        """Auto-approve all changes and return signed baseline YAML."""
        try:
            result = api.auto_approve_run(
                run_id=UUID(pk),
                user_id=cast(int, request.user.id),
                team_id=self.team_id,
            )
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        except api.StaleRunError as e:
            return Response(
                {"detail": str(e), "code": "stale_run"},
                status=status.HTTP_409_CONFLICT,
            )
        except api.ArtifactNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AutoApproveResultSerializer(instance=result).data)
