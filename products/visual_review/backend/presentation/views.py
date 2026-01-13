"""
DRF views for visual_review.

Responsibilities:
- Validate incoming JSON (via serializers)
- Convert JSON to DTOs
- Call facade methods (api/api.py)
- Convert DTOs to JSON responses

No business logic here - that belongs in logic.py via the facade.
"""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..api import api
from ..api.dtos import ApproveRunInput, RegisterArtifactInput
from .serializers import (
    ApproveRunInputSerializer,
    ArtifactSerializer,
    ArtifactUploadedSerializer,
    CreateRunInputSerializer,
    CreateRunResultSerializer,
    ProjectSerializer,
    RunSerializer,
    SnapshotSerializer,
    UploadUrlRequestSerializer,
    UploadUrlSerializer,
)

# TODO: Add VISUAL_REVIEW to frontend/src/queries/schema/schema-general.ts ProductKey enum
# and regenerate posthog/schema.py, then use ProductKey.VISUAL_REVIEW here
VISUAL_REVIEW_TAG = "visual_review"


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class ProjectViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Projects for visual review.

    A project typically represents a repository or test suite.
    """

    scope_object = "INTERNAL"

    @extend_schema(responses={200: ProjectSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List all projects for the team."""
        projects = api.list_projects(self.team_id)
        return Response(ProjectSerializer(instance=projects, many=True).data)

    @extend_schema(responses={201: ProjectSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        """Create a new project."""
        name = request.data.get("name")
        project = api.create_project(team_id=self.team_id, name=name)
        return Response(ProjectSerializer(instance=project).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: ProjectSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Get a project by ID."""
        try:
            project = api.get_project(UUID(pk))
        except api.ProjectNotFoundError:
            return Response({"detail": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(ProjectSerializer(instance=project).data)

    @extend_schema(request=UploadUrlRequestSerializer, responses={200: UploadUrlSerializer})
    @action(detail=True, methods=["post"], url_path="upload-url")
    def get_upload_url(self, request: Request, pk: str, **kwargs) -> Response:
        """Get a presigned URL for uploading an artifact."""
        serializer = UploadUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        upload_url = api.get_upload_url(UUID(pk), serializer.validated_data["content_hash"])
        if not upload_url:
            return Response({"detail": "Object storage not available"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(UploadUrlSerializer(instance=upload_url).data)

    @extend_schema(request=ArtifactUploadedSerializer, responses={201: ArtifactSerializer})
    @action(detail=True, methods=["post"], url_path="artifacts")
    def register_artifact(self, request: Request, pk: str, **kwargs) -> Response:
        """Register an artifact after it has been uploaded to S3."""
        serializer = ArtifactUploadedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        project_id = UUID(pk)
        data = serializer.validated_data

        # Build storage path from project_id and hash
        from ..storage import ArtifactStorage

        storage = ArtifactStorage(str(project_id))
        storage_path = storage._key(data["content_hash"])

        artifact = api.register_artifact(
            RegisterArtifactInput(
                project_id=project_id,
                content_hash=data["content_hash"],
                storage_path=storage_path,
                width=data.get("width"),
                height=data.get("height"),
                size_bytes=data.get("size_bytes"),
            )
        )

        return Response({"id": str(artifact.id), "content_hash": artifact.content_hash}, status=status.HTTP_201_CREATED)


@extend_schema(tags=[VISUAL_REVIEW_TAG])
class RunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Visual review runs.

    A run represents a single CI execution that captures screenshots.
    """

    scope_object = "INTERNAL"

    @extend_schema(request=CreateRunInputSerializer, responses={201: CreateRunResultSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        """Create a new run from a CI manifest."""
        serializer = CreateRunInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # DataclassSerializer returns a CreateRunInput dataclass directly
        input_dto = serializer.validated_data
        result = api.create_run(input_dto)
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

    @extend_schema(request=ApproveRunInputSerializer, responses={200: RunSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str, **kwargs) -> Response:
        """Approve visual changes for snapshots in this run."""
        serializer = ApproveRunInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        # ApproveSnapshotInputSerializer returns ApproveSnapshotInput dataclass objects
        input_dto = ApproveRunInput(
            run_id=UUID(pk),
            user_id=request.user.id,
            snapshots=data["snapshots"],  # Already a list of ApproveSnapshotInput
        )

        try:
            run = api.approve_run(input_dto)
        except api.RunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(RunSerializer(instance=run).data)
