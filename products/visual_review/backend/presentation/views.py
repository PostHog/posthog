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

from ..facade import api, contracts
from ..facade.contracts import (
    AddSnapshotsInput,
    ApproveRunInput,
    ApproveRunRequestInput,
    CreateRepoInput,
    CreateRunInput,
    QuarantineInput,
    UpdateRepoInput,
    UpdateRepoRequestInput,
)
from ..facade.enums import ReviewDecision
from .serializers import (
    AddSnapshotsInputSerializer,
    AddSnapshotsResultSerializer,
    ApproveRunInputSerializer,
    AutoApproveResultSerializer,
    CreateRepoInputSerializer,
    CreateRunInputSerializer,
    CreateRunResultSerializer,
    MarkToleratedInputSerializer,
    QuarantinedIdentifierEntrySerializer,
    QuarantineInputSerializer,
    RepoSerializer,
    ReviewStateCountsSerializer,
    RunSerializer,
    SnapshotHistoryEntrySerializer,
    SnapshotSerializer,
    ToleratedHashEntrySerializer,
    UnquarantineQuerySerializer,
    UpdateRepoInputSerializer,
)

VISUAL_REVIEW_TAG = "visual_review"


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class RepoViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Projects for visual review.

    A repo typically represents a repository or test suite.
    """

    scope_object = "visual_review"
    scope_object_write_actions = ["create", "partial_update", "quarantine", "unquarantine"]
    scope_object_read_actions = ["list", "retrieve", "list_quarantined"]

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
            enable_pr_comments=body.enable_pr_comments,
        )

        try:
            repo = api.update_repo(input_dto, team_id=self.team_id)
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RepoSerializer(instance=repo).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="identifier", type=str, required=False, description="Filter by identifier (returns full history)"
            ),
            OpenApiParameter(name="run_type", type=str, required=False, description="Filter by run type"),
        ],
        responses={200: QuarantinedIdentifierEntrySerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="quarantine")
    def list_quarantined(self, request: Request, pk: str, **kwargs) -> Response:
        """List quarantined identifiers. Without filter: active only. With identifier: full history."""
        identifier = request.query_params.get("identifier")
        run_type = request.query_params.get("run_type")
        entries = api.list_quarantined(UUID(pk), team_id=self.team_id, identifier=identifier, run_type=run_type)
        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = QuarantinedIdentifierEntrySerializer(instance=page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(QuarantinedIdentifierEntrySerializer(instance=entries, many=True).data)

    @validated_request(
        request_serializer=QuarantineInputSerializer,
        responses={201: OpenApiResponse(response=QuarantinedIdentifierEntrySerializer)},
    )
    @action(detail=True, methods=["post"], url_path=r"quarantine/(?P<run_type>[^/]+)")
    def quarantine(self, request: TypedRequest[QuarantineInput], pk: str, run_type: str, **kwargs) -> Response:
        """Quarantine a snapshot identifier for a specific run type."""
        try:
            entry = api.quarantine_identifier(
                repo_id=UUID(pk),
                run_type=run_type,
                input=request.validated_data,
                user_id=cast(int, request.user.id),
                team_id=self.team_id,
            )
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(QuarantinedIdentifierEntrySerializer(instance=entry).data, status=status.HTTP_201_CREATED)

    @validated_request(
        query_serializer=UnquarantineQuerySerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["delete"], url_path=r"quarantine/(?P<run_type>[^/]+)")
    def unquarantine(self, request: Request, pk: str, run_type: str, **kwargs) -> Response:
        """Remove an identifier from quarantine."""
        identifier = request.validated_query_data["identifier"]
        try:
            api.unquarantine_identifier(
                repo_id=UUID(pk), identifier=identifier, run_type=run_type, team_id=self.team_id
            )
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class RunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Visual review runs.

    A run represents a single CI execution that captures screenshots.
    """

    scope_object = "visual_review"
    scope_object_write_actions = ["create", "complete", "approve", "auto_approve", "add_snapshots"]
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

    @validated_request(
        request_serializer=MarkToleratedInputSerializer,
        responses={200: OpenApiResponse(response=SnapshotSerializer)},
    )
    @action(detail=True, methods=["post"], url_path="tolerate")
    def mark_tolerated(self, request: TypedRequest, pk: str, **kwargs) -> Response:
        """Mark a changed snapshot as a known tolerated alternate."""
        try:
            snapshot = api.mark_snapshot_as_tolerated(
                run_id=UUID(pk),
                snapshot_id=request.validated_data["snapshot_id"],
                user_id=cast(int, request.user.id),
                team_id=self.team_id,
            )
        except api.RunNotFoundError:
            return Response({"detail": "Snapshot or run not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({"detail": "Snapshot cannot be marked as tolerated"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SnapshotSerializer(instance=snapshot).data)

    @extend_schema(
        parameters=[OpenApiParameter("identifier", str, required=True, description="Snapshot identifier")],
        responses={200: ToleratedHashEntrySerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="tolerated-hashes")
    def tolerated_hashes(self, request: Request, pk: str, **kwargs) -> Response:
        """List known tolerated hashes for a snapshot identifier."""
        identifier = request.query_params.get("identifier")
        if not identifier:
            return Response({"detail": "identifier query param required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            run = api.get_run(UUID(pk), team_id=self.team_id)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        entries = api.get_tolerated_hashes(run.repo_id, identifier)
        page = self.paginate_queryset(entries)
        if page is not None:
            return self.get_paginated_response(ToleratedHashEntrySerializer(instance=page, many=True).data)
        return Response(ToleratedHashEntrySerializer(instance=entries, many=True).data)

    @extend_schema(request=AddSnapshotsInputSerializer, responses={200: AddSnapshotsResultSerializer})
    @action(detail=True, methods=["post"], url_path="add-snapshots")
    @validated_request(AddSnapshotsInputSerializer)
    def add_snapshots(self, request: TypedRequest[AddSnapshotsInput], pk: str, **kwargs) -> Response:
        """Add a batch of snapshots to a pending run (shard-based flow)."""
        try:
            result = api.add_snapshots(
                input=request.validated_data,
                run_id=UUID(pk),
                team_id=self.team_id,
            )
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({"detail": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AddSnapshotsResultSerializer(instance=result).data)

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
        """Complete a run: detect removals, verify uploads, trigger diff processing."""
        try:
            run = api.complete_run(UUID(pk), team_id=self.team_id)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RunSerializer(instance=run).data)

    @validated_request(
        request_serializer=ApproveRunInputSerializer,
        responses={200: OpenApiResponse(response=AutoApproveResultSerializer)},
    )
    @action(detail=True, methods=["post"])
    def approve(self, request: TypedRequest[ApproveRunRequestInput], pk: str, **kwargs) -> Response:
        """Approve visual changes for snapshots in this run.

        With approve_all=true, approves all changed+new snapshots and returns
        signed baseline YAML. With specific snapshots, approves only those.
        """
        body = request.validated_data
        run_id = UUID(pk)
        user_id = cast(int, request.user.id)

        try:
            if body.approve_all:
                result = api.approve_all(run_id=run_id, user_id=user_id, team_id=self.team_id)
                return Response(AutoApproveResultSerializer(instance=result).data)

            input_dto = ApproveRunInput(
                run_id=run_id,
                user_id=user_id,
                snapshots=body.snapshots,
                commit_to_github=body.commit_to_github,
            )
            run = api.approve_run(input_dto, team_id=self.team_id)
            return Response(
                AutoApproveResultSerializer(instance=contracts.AutoApproveResult(run=run, baseline_content="")).data
            )

        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        except api.StaleRunError as e:
            return Response({"detail": str(e), "code": "stale_run"}, status=status.HTTP_409_CONFLICT)
        except api.ArtifactNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except api.GitHubIntegrationNotFoundError:
            return Response(
                {"detail": "No GitHub integration configured. Please install the GitHub App for this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except api.PRSHAMismatchError as e:
            return Response({"detail": str(e), "code": "sha_mismatch"}, status=status.HTTP_409_CONFLICT)
        except api.GitHubCommitError as e:
            return Response({"detail": f"GitHub commit failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)
        except api.BaselineFilePathNotConfiguredError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({"detail": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(responses={200: AutoApproveResultSerializer}, deprecated=True)
    @action(detail=True, methods=["post"], url_path="auto-approve")
    def auto_approve(self, request: Request, pk: str, **kwargs) -> Response:
        """CLI auto-approve: approve all and return baseline YAML for local write."""
        try:
            result = api.approve_all(
                run_id=UUID(pk),
                user_id=cast(int, request.user.id),
                team_id=self.team_id,
                review_decision=ReviewDecision.AUTO_APPROVED,
                commit_to_github=False,
            )
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        except api.StaleRunError as e:
            return Response({"detail": str(e), "code": "stale_run"}, status=status.HTTP_409_CONFLICT)
        except api.ArtifactNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({"detail": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AutoApproveResultSerializer(instance=result).data)
