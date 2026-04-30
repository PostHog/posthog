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

from django.http import HttpResponse
from django.utils.cache import get_conditional_response, patch_cache_control, patch_vary_headers

from drf_spectacular.types import OpenApiTypes
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
    BaselineOverviewSerializer,
    CreateRepoInputSerializer,
    CreateRunInputSerializer,
    CreateRunResultSerializer,
    MarkToleratedInputSerializer,
    QuarantinedIdentifierEntrySerializer,
    QuarantineInputSerializer,
    RecomputeResultSerializer,
    RepoSerializer,
    ReviewStateCountsSerializer,
    RunSerializer,
    SnapshotHistoryEntrySerializer,
    SnapshotSerializer,
    ToleratedHashEntrySerializer,
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
    scope_object_read_actions = [
        "list",
        "retrieve",
        "list_quarantined",
        "thumbnail",
        "baselines",
    ]

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

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={200: RepoSerializer},
    )
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Get a repo by ID."""
        try:
            repo = api.get_repo(UUID(pk), team_id=self.team_id)
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RepoSerializer(instance=repo).data)

    @extend_schema(parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)])
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
            OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH),
            OpenApiParameter("identifier", OpenApiTypes.STR, OpenApiParameter.PATH),
        ],
        responses={200: OpenApiResponse(description="WebP thumbnail image")},
    )
    @action(detail=True, methods=["get"], url_path=r"thumbnails/(?P<identifier>.+[^/])")
    def thumbnail(self, request: Request, pk: str, identifier: str, **kwargs) -> HttpResponse:
        """Serve a snapshot thumbnail by identifier. Returns WebP with ETag caching."""
        try:
            api.get_repo(UUID(pk), team_id=self.team_id)
        except api.RepoNotFoundError:
            resp = HttpResponse(status=404)
            patch_cache_control(resp, no_store=True)
            return resp

        thumb_hash = api.get_thumbnail_hash_for_identifier(UUID(pk), identifier)
        if thumb_hash is None:
            resp = HttpResponse(status=404)
            patch_cache_control(resp, no_store=True)
            return resp

        etag = f'"{thumb_hash}"'
        not_modified = get_conditional_response(request._request, etag=etag)
        if not_modified:
            # Shared caches must key on credentials — see thumbnail success path below.
            patch_vary_headers(not_modified, ["Authorization", "Cookie"])
            return not_modified

        thumb_bytes = api.read_thumbnail_bytes(UUID(pk), thumb_hash)
        if thumb_bytes is None:
            resp = HttpResponse(status=404)
            patch_cache_control(resp, no_store=True)
            return resp

        response = HttpResponse(thumb_bytes, content_type="image/webp")
        response["ETag"] = etag
        # Endpoint is auth-scoped (team), so Vary on credential headers prevents shared
        # caches from serving the same URL across tenants.
        patch_vary_headers(response, ["Authorization", "Cookie"])
        patch_cache_control(response, public=True, max_age=300, stale_while_revalidate=3600)
        return response

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
        request_serializer=QuarantineInputSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path=r"quarantine/(?P<run_type>[^/]+)/expire")
    def unquarantine(self, request: TypedRequest[QuarantineInput], pk: str, run_type: str, **kwargs) -> Response:
        """Expire all active quarantine entries for an identifier."""
        try:
            api.unquarantine_identifier(
                repo_id=UUID(pk),
                identifier=request.validated_data.identifier,
                run_type=run_type,
                team_id=self.team_id,
            )
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={200: BaselineOverviewSerializer},
        description=(
            "Snapshots overview for a repo: every identifier with a current baseline (latest "
            "non-superseded master/main run per run_type), plus tolerate counts, active "
            "quarantine state, and a 30-day stability sparkline. Capped at "
            f"{contracts.BASELINE_OVERVIEW_MAX_ENTRIES} entries — sets `truncated` and "
            "returns the most recently active when exceeded. Filtering / faceting / search are "
            "all done client-side; this endpoint takes no filter query params."
        ),
    )
    @action(detail=True, methods=["get"], url_path="baselines")
    def baselines(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            api.get_repo(UUID(pk), team_id=self.team_id)
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        result = api.get_baselines_overview(UUID(pk))
        return Response(BaselineOverviewSerializer(instance=result).data)


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class SnapshotViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Snapshot identities under a repo, keyed by (run_type, identifier).

    A "snapshot identity" doesn't have a single canonical row — it's a series
    of `RunSnapshot` rows over time. The retrieve-style endpoint returns the
    deduped baseline timeline for that identity, which is the most useful view.

    `identifier` is a path segment — clients must percent-encode before sending
    (`encodeURIComponent`). Django/ASGI URL-decode the kwarg automatically.
    """

    scope_object = "visual_review"
    scope_object_read_actions = ["timeline"]

    @extend_schema(
        parameters=[
            OpenApiParameter("run_type", str, OpenApiParameter.PATH, description="Run type (storybook, playwright)"),
            OpenApiParameter(
                "identifier",
                str,
                OpenApiParameter.PATH,
                description="Snapshot identifier; clients must percent-encode before sending",
            ),
        ],
        responses={200: SnapshotHistoryEntrySerializer(many=True)},
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"(?P<run_type>[^/]+)/(?P<identifier>[^/]+)",
    )
    def timeline(self, request: Request, run_type: str, identifier: str, **kwargs) -> Response:
        """Deduped baseline timeline for a snapshot identity. Newest first."""
        repo_id = UUID(self.parents_query_dict["repo_id"])
        try:
            api.get_repo(repo_id, team_id=self.team_id)
        except api.RepoNotFoundError:
            return Response({"detail": "Repo not found"}, status=status.HTTP_404_NOT_FOUND)
        history = api.get_snapshot_history(repo_id, identifier, run_type)
        page = self.paginate_queryset(history)
        if page is not None:
            return self.get_paginated_response(SnapshotHistoryEntrySerializer(instance=page, many=True).data)
        return Response(SnapshotHistoryEntrySerializer(instance=history, many=True).data)


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class RepoRunsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Listing/aggregation of runs scoped to a single repo.

    Run-by-id actions (retrieve, snapshots, approve, complete, etc.) live on
    the flat `RunViewSet` so that direct links by run id keep working without
    forcing the repo into the path.
    """

    scope_object = "visual_review"
    scope_object_read_actions = ["list", "counts"]
    serializer_class = RunSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("review_state", str, required=False, description="Filter by review state"),
        ],
        responses={200: RunSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        """List runs in this repo, optionally filtered by review state."""
        review_state = request.query_params.get("review_state")
        repo_id = UUID(self.parents_query_dict["repo_id"])
        runs = api.list_runs(self.team_id, review_state=review_state, repo_id=repo_id)
        page = self.paginate_queryset(runs)
        if page is not None:
            serializer = RunSerializer(instance=page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(RunSerializer(instance=runs, many=True).data)

    @extend_schema(responses={200: ReviewStateCountsSerializer})
    @action(detail=False, methods=["get"])
    def counts(self, request: Request, **kwargs) -> Response:
        """Review state counts for runs in this repo."""
        repo_id = UUID(self.parents_query_dict["repo_id"])
        return Response(api.get_review_state_counts(self.team_id, repo_id=repo_id))


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class RunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Visual review runs.

    A run represents a single CI execution that captures screenshots.
    """

    scope_object = "visual_review"
    scope_object_write_actions = ["create", "complete", "approve", "auto_approve", "add_snapshots", "recompute"]
    scope_object_read_actions = ["list", "retrieve", "snapshots", "counts", "snapshot_history", "tolerated_hashes"]
    serializer_class = RunSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("review_state", str, required=False, description="Filter by review state"),
            OpenApiParameter("pr_number", int, required=False, description="Filter by GitHub PR number"),
            OpenApiParameter("commit_sha", str, required=False, description="Filter by full commit SHA"),
            OpenApiParameter("branch", str, required=False, description="Filter by branch name"),
        ],
        responses={200: RunSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        """List runs for the team, optionally filtered by review state, PR number, commit SHA, or branch."""
        pr_number_raw = request.query_params.get("pr_number")
        try:
            pr_number = int(pr_number_raw) if pr_number_raw is not None else None
        except ValueError:
            return Response({"detail": "pr_number must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        runs = api.list_runs(
            self.team_id,
            review_state=request.query_params.get("review_state"),
            pr_number=pr_number,
            commit_sha=request.query_params.get("commit_sha"),
            branch=request.query_params.get("branch"),
        )
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

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={200: RunSerializer},
    )
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

        history = api.get_snapshot_history(run.repo_id, identifier, run.run_type)
        page = self.paginate_queryset(history)
        if page is not None:
            return self.get_paginated_response(SnapshotHistoryEntrySerializer(instance=page, many=True).data)
        return Response(SnapshotHistoryEntrySerializer(instance=history, many=True).data)

    @extend_schema(request=None, responses={200: RunSerializer})
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str, **kwargs) -> Response:
        """Complete a run: detect removals, verify uploads, trigger diff processing."""
        try:
            run = api.complete_run(UUID(pk), team_id=self.team_id)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        except api.GitHubRateLimitError as e:
            response = Response(
                {"detail": "GitHub API rate limit exceeded. Please retry later.", "code": "rate_limited"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            if e.retry_after:
                response["Retry-After"] = str(e.retry_after)
            return response
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
        except api.GitHubRateLimitError as e:
            response = Response(
                {"detail": "GitHub API rate limit exceeded. Please retry later.", "code": "rate_limited"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            if e.retry_after:
                response["Retry-After"] = str(e.retry_after)
            return response
        except api.GitHubCommitError:
            return Response({"detail": "GitHub commit failed"}, status=status.HTTP_502_BAD_GATEWAY)

    @extend_schema(
        request=None,
        responses={200: RecomputeResultSerializer},
        description="Re-evaluate quarantine and counts, update commit status, and optionally rerun the CI job.",
    )
    @action(detail=True, methods=["post"], url_path="recompute")
    def recompute(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            result = api.recompute_run(UUID(pk), team_id=self.team_id)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response(
                {"detail": "Run must be completed and not yet approved"}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(RecomputeResultSerializer(instance=result).data)

    @extend_schema(request=None, responses={200: AutoApproveResultSerializer}, deprecated=True)
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
