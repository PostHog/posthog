"""The bundled files inside a skill: read one, add one, delete one, rename one.

Every write here publishes a new version of the skill, so they share the version-conflict and
version-limit contract of a publish.
"""

from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.models import User

from products.ai_observability.backend.api.metrics import llma_track_latency

from ..models.skills import LLMSkillFile
from .skill_analytics import file_extension, record_skill_event, skill_analytics_props
from .skill_error_responses import skill_not_found_response, skill_write_error_response
from .skill_serializers import (
    LLMSkillFetchQuerySerializer,
    LLMSkillFileCreateSerializer,
    LLMSkillFileDeleteQuerySerializer,
    LLMSkillFileRenameSerializer,
    LLMSkillFileSerializer,
    LLMSkillSerializer,
)
from .skill_services import (
    LLMSkillDescriptionTooLongError,
    LLMSkillFileLimitError,
    LLMSkillFileNotFoundError,
    LLMSkillFilePathConflictError,
    LLMSkillNotFoundError,
    LLMSkillVersionConflictError,
    LLMSkillVersionLimitError,
    create_skill_file,
    delete_skill_file,
    rename_skill_file,
)
from .skill_view_access import SkillAccessMixin


def _safe_file_path(file_path: str) -> str | None:
    """The path without its trailing slashes, or None when it tries to escape the skill."""
    file_path = file_path.rstrip("/")
    normalized = file_path.replace("\\", "/")
    if ".." in normalized.split("/") or normalized.startswith("/"):
        return None
    return file_path


# The `name/<slug>/files` endpoints.
class SkillFileActionsMixin(SkillAccessMixin):
    @extend_schema(
        parameters=[LLMSkillFetchQuerySerializer],
        responses={200: LLMSkillFileSerializer},
    )
    # NOTE: `required_scopes` is intentionally not set on @action here. delete_file is registered
    # below via @get_file.mapping.delete and shares this URL pattern's initkwargs — setting
    # required_scopes here would short-circuit ScopeBasePermission._get_required_scopes for DELETE
    # too, granting llm_skill:read access to a destructive operation. Scopes are resolved per-method
    # in dangerously_get_required_scopes instead.
    @action(
        methods=["GET"],
        detail=False,
        url_path=r"name/(?P<skill_name>[^/]+)/files/(?P<file_path>.+)",
    )
    @llma_track_latency("llma_skills_get_file")
    @monitor(feature=None, endpoint="llma_skills_get_file", method="GET")
    def get_file(self, request: Request, skill_name: str = "", file_path: str = "", **kwargs) -> Response:
        version_params = self._validated_query(LLMSkillFetchQuerySerializer, request)
        version = cast(int | None, version_params.get("version"))
        skill = self._load_skill_with_object_access(request, skill_name, version)
        if skill is None:
            return skill_not_found_response(skill_name)

        safe_path = _safe_file_path(file_path)
        if safe_path is None:
            return Response({"detail": "Invalid file path."}, status=status.HTTP_400_BAD_REQUEST)
        file_path = safe_path
        skill_file = LLMSkillFile.objects.filter(skill=skill, path=file_path).first()
        if skill_file is None:
            return Response(
                {"detail": f"File '{file_path}' not found in skill '{skill_name}'."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(LLMSkillFileSerializer(skill_file).data)

    @extend_schema(request=LLMSkillFileCreateSerializer, responses={201: LLMSkillSerializer})
    @action(
        methods=["POST"],
        detail=False,
        url_path=r"name/(?P<skill_name>[^/]+)/files",
        required_scopes=["llm_skill:write"],
    )
    @llma_track_latency("llma_skills_create_file")
    @monitor(feature=None, endpoint="llma_skills_create_file", method="POST")
    def create_file(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        access_error = self._guard_object_access(request, skill_name)
        if access_error is not None:
            return access_error

        payload = LLMSkillFileCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            published_skill = create_skill_file(
                self.team,
                user=cast(User, request.user),
                skill_name=skill_name,
                path=payload.validated_data["path"],
                content=payload.validated_data["content"],
                content_type=payload.validated_data.get("content_type", "text/plain"),
                base_version=payload.validated_data.get("base_version"),
            )
        except (
            LLMSkillNotFoundError,
            LLMSkillVersionConflictError,
            LLMSkillVersionLimitError,
            LLMSkillFileLimitError,
            LLMSkillDescriptionTooLongError,
        ) as err:
            response = skill_write_error_response(err, skill_name)
            if response is None:
                raise
            return response
        except LLMSkillFilePathConflictError as err:
            return Response(
                {"detail": f"File '{err.path}' already exists in skill '{skill_name}'."},
                status=status.HTTP_409_CONFLICT,
            )

        path_value = payload.validated_data["path"]
        content_value = payload.validated_data["content"]
        props = {
            **skill_analytics_props(published_skill),
            "path": path_value,
            "content_type": payload.validated_data.get("content_type", "text/plain"),
            "file_content_length": len(content_value),
            "file_extension": file_extension(path_value),
        }
        record_skill_event(
            log_event="llma_skill_file_created",
            action="llma skill file created",
            user=cast(User, request.user),
            team=self.team,
            request=request,
            props=props,
        )
        return Response(self._serialize_skill(published_skill), status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[LLMSkillFileDeleteQuerySerializer], responses={200: LLMSkillSerializer})
    @get_file.mapping.delete
    @llma_track_latency("llma_skills_delete_file")
    @monitor(feature=None, endpoint="llma_skills_delete_file", method="DELETE")
    def delete_file(self, request: Request, skill_name: str = "", file_path: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        access_error = self._guard_object_access(request, skill_name)
        if access_error is not None:
            return access_error

        safe_path = _safe_file_path(file_path)
        if safe_path is None:
            return Response({"detail": "Invalid file path."}, status=status.HTTP_400_BAD_REQUEST)
        file_path = safe_path

        query = LLMSkillFileDeleteQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        try:
            published_skill = delete_skill_file(
                self.team,
                user=cast(User, request.user),
                skill_name=skill_name,
                path=file_path,
                base_version=query.validated_data.get("base_version"),
            )
        except (
            LLMSkillNotFoundError,
            LLMSkillVersionConflictError,
            LLMSkillVersionLimitError,
            LLMSkillFileLimitError,
            LLMSkillDescriptionTooLongError,
        ) as err:
            response = skill_write_error_response(err, skill_name)
            if response is None:
                raise
            return response
        except LLMSkillFileNotFoundError as err:
            return Response(
                {"detail": f"File '{err.path}' not found in skill '{skill_name}'."},
                status=status.HTTP_404_NOT_FOUND,
            )

        props = {
            **skill_analytics_props(published_skill),
            "path": file_path,
            "file_extension": file_extension(file_path),
        }
        record_skill_event(
            log_event="llma_skill_file_deleted",
            action="llma skill file deleted",
            user=cast(User, request.user),
            team=self.team,
            request=request,
            props=props,
        )
        return Response(self._serialize_skill(published_skill))

    @extend_schema(request=LLMSkillFileRenameSerializer, responses={200: LLMSkillSerializer})
    @action(
        methods=["POST"],
        detail=False,
        url_path=r"name/(?P<skill_name>[^/]+)/files-rename",
        required_scopes=["llm_skill:write"],
    )
    @llma_track_latency("llma_skills_rename_file")
    @monitor(feature=None, endpoint="llma_skills_rename_file", method="POST")
    def rename_file(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        access_error = self._guard_object_access(request, skill_name)
        if access_error is not None:
            return access_error

        payload = LLMSkillFileRenameSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            published_skill = rename_skill_file(
                self.team,
                user=cast(User, request.user),
                skill_name=skill_name,
                old_path=payload.validated_data["old_path"],
                new_path=payload.validated_data["new_path"],
                base_version=payload.validated_data.get("base_version"),
            )
        except (
            LLMSkillNotFoundError,
            LLMSkillVersionConflictError,
            LLMSkillVersionLimitError,
            LLMSkillFileLimitError,
            LLMSkillDescriptionTooLongError,
        ) as err:
            response = skill_write_error_response(err, skill_name)
            if response is None:
                raise
            return response
        except LLMSkillFileNotFoundError as err:
            return Response(
                {"detail": f"File '{err.path}' not found in skill '{skill_name}'."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except LLMSkillFilePathConflictError as err:
            return Response(
                {"detail": f"File '{err.path}' already exists in skill '{skill_name}'."},
                status=status.HTTP_409_CONFLICT,
            )

        old_path_value = payload.validated_data["old_path"]
        new_path_value = payload.validated_data["new_path"]
        old_extension = file_extension(old_path_value)
        new_extension = file_extension(new_path_value)
        props = {
            **skill_analytics_props(published_skill),
            "old_path": old_path_value,
            "new_path": new_path_value,
            "old_file_extension": old_extension,
            "new_file_extension": new_extension,
            "extension_changed": old_extension != new_extension,
        }
        record_skill_event(
            log_event="llma_skill_file_renamed",
            action="llma skill file renamed",
            user=cast(User, request.user),
            team=self.team,
            request=request,
            props=props,
        )
        return Response(self._serialize_skill(published_skill))
