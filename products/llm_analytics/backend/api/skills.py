from typing import Any, cast

from django.db import IntegrityError
from django.db.models import Q, QuerySet

import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import (
    JwtAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
)
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import AccessControlPermission, get_organization_from_view
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from ..models.skills import LLMSkill, LLMSkillFile
from .metrics import llma_track_latency
from .skill_serializers import (
    LLMSkillCreateSerializer,
    LLMSkillDuplicateSerializer,
    LLMSkillFetchQuerySerializer,
    LLMSkillFileCreateSerializer,
    LLMSkillFileDeleteQuerySerializer,
    LLMSkillFileRenameSerializer,
    LLMSkillFileSerializer,
    LLMSkillListQuerySerializer,
    LLMSkillListSerializer,
    LLMSkillPublishSerializer,
    LLMSkillResolveQuerySerializer,
    LLMSkillResolveResponseSerializer,
    LLMSkillSerializer,
    LLMSkillVersionSummarySerializer,
)
from .skill_services import (
    LLMSkillDuplicateNameConflictError,
    LLMSkillEditError,
    LLMSkillFileLimitError,
    LLMSkillFileNotFoundError,
    LLMSkillFilePathConflictError,
    LLMSkillNotFoundError,
    LLMSkillVersionConflictError,
    LLMSkillVersionLimitError,
    archive_skill,
    create_skill_file,
    delete_skill_file,
    duplicate_skill,
    get_active_skill_queryset,
    get_latest_skills_queryset,
    get_skill_by_name_from_db,
    publish_skill_version,
    rename_skill_file,
    resolve_versions_page,
)

LLM_SKILL_FEATURE_FLAG = "llm-analytics-skills"


class LLMSkillFeatureFlagPermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = cast(User, request.user)
        organization = get_organization_from_view(view)
        org_id = str(organization.id)
        distinct_id = user.distinct_id or str(user.uuid)

        return bool(
            posthoganalytics.feature_enabled(
                LLM_SKILL_FEATURE_FLAG,
                distinct_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )


ALLOWED_LIST_ORDERINGS = frozenset(
    {
        "name",
        "-name",
        "created_at",
        "-created_at",
        "updated_at",
        "-updated_at",
        "version",
        "-version",
        "latest_version",
        "-latest_version",
        "version_count",
        "-version_count",
    }
)


@extend_schema(tags=["llm_analytics"])
class LLMSkillViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "llm_skill"
    queryset = LLMSkill.objects.all()
    serializer_class = LLMSkillSerializer
    permission_classes = [LLMSkillFeatureFlagPermission, AccessControlPermission]

    def safely_get_queryset(self, queryset: QuerySet[LLMSkill]) -> QuerySet[LLMSkill]:
        return get_active_skill_queryset(self.team)

    def get_throttles(self):
        if self.action in ["update_by_name", "get_by_name", "resolve_by_name"]:
            return [BurstRateThrottle(), SustainedRateThrottle()]
        return super().get_throttles()

    # Differentiates read vs write scopes for GET/PATCH on the shared /name/<slug> URL
    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        super_method = getattr(super(), "dangerously_get_required_scopes", None)
        if callable(super_method):
            mixin_result = super_method(request, view)
            if mixin_result is not None:
                return mixin_result

        if view.action in ["get_by_name", "update_by_name"]:
            return ["llm_skill:write"] if request.method == "PATCH" else ["llm_skill:read"]
        # get_file and delete_file share a URL via @get_file.mapping.delete. We deliberately do
        # NOT set required_scopes on get_file's @action — see the note there. Resolve per-method:
        # GET (and HEAD, which DRF auto-routes to GET handlers) → read, DELETE → write.
        if view.action in ["get_file", "delete_file"]:
            if request.method == "DELETE":
                return ["llm_skill:write"]
            if request.method in ("GET", "HEAD"):
                return ["llm_skill:read"]
        return None

    def _ensure_web_authenticated(self, request: Request) -> Response | None:
        if not isinstance(
            request.successful_authenticator,
            SessionAuthentication | JwtAuthentication | PersonalAPIKeyAuthentication | OAuthAccessTokenAuthentication,
        ):
            return Response(
                {"detail": "This endpoint is only available to web-authenticated users."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _skill_not_found_response(self, skill_name: str) -> Response:
        return Response(
            {"detail": f"Skill with name '{skill_name}' not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    def _handle_skill_write_error(self, err: Exception, skill_name: str) -> Response | None:
        """Render the error responses shared by create_file / delete_file / rename_file.

        Returns None if the error is not one of the shared ones — callers re-raise.
        """
        if isinstance(err, LLMSkillNotFoundError):
            return self._skill_not_found_response(skill_name)
        if isinstance(err, LLMSkillVersionConflictError):
            return Response(
                {
                    "detail": "The skill changed since you opened it. Reload the latest version and try again.",
                    "current_version": err.current_version,
                },
                status=status.HTTP_409_CONFLICT,
            )
        if isinstance(err, LLMSkillVersionLimitError):
            return Response(
                {
                    "detail": (
                        f"Skill has reached the maximum of {err.max_version} versions. "
                        "Archive and recreate the skill to continue publishing."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if isinstance(err, LLMSkillFileLimitError):
            return Response(
                {"detail": f"Skill has reached the maximum of {err.max_count} files."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

    def _serialize_skill(self, skill: LLMSkill) -> dict[str, Any]:
        return cast(dict[str, Any], LLMSkillSerializer(skill, context=self.get_serializer_context()).data)

    def _serialize_version_summaries(self, skills: list[LLMSkill]) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], LLMSkillVersionSummarySerializer(skills, many=True).data)

    def _get_requested_version_params(self, request: Request) -> dict[str, Any]:
        serializer = LLMSkillFetchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _get_resolve_query_params(self, request: Request) -> dict[str, Any]:
        serializer = LLMSkillResolveQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _get_list_params(self, request: Request) -> dict[str, Any]:
        serializer = LLMSkillListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _get_list_queryset(self, request: Request) -> QuerySet[LLMSkill]:
        params = self._get_list_params(request)

        queryset = get_latest_skills_queryset(self.team)

        search = params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))

        created_by_id = params.get("created_by_id")
        if created_by_id:
            queryset = queryset.filter(created_by_id=created_by_id)

        order_by = request.query_params.get("order_by", "-created_at")
        queryset = queryset.order_by(order_by if order_by in ALLOWED_LIST_ORDERINGS else "-created_at", "-id")
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return LLMSkillListSerializer
        if self.action == "create":
            return LLMSkillCreateSerializer
        return super().get_serializer_class()

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        instance = cast(LLMSkill, serializer.save())

        report_user_action(
            cast(User, self.request.user),
            "llma skill created",
            {
                "skill_id": str(instance.id),
                "skill_name": instance.name,
                "skill_version": instance.version,
            },
            team=self.team,
            request=self.request,
        )

    @extend_schema(
        parameters=[LLMSkillFetchQuerySerializer],
        responses={200: LLMSkillSerializer},
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<skill_name>[^/]+)")
    @llma_track_latency("llma_skills_get_by_name")
    @monitor(feature=None, endpoint="llma_skills_get_by_name", method="GET")
    def get_by_name(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        version_params = self._get_requested_version_params(request)
        version = cast(int | None, version_params.get("version"))
        skill = get_skill_by_name_from_db(self.team, skill_name, version)
        if skill is None:
            return self._skill_not_found_response(skill_name)

        return Response(self._serialize_skill(skill))

    @extend_schema(request=LLMSkillPublishSerializer, responses={200: LLMSkillSerializer})
    @get_by_name.mapping.patch
    @llma_track_latency("llma_skills_publish_by_name")
    @monitor(feature=None, endpoint="llma_skills_publish_by_name", method="PATCH")
    def update_by_name(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        payload = LLMSkillPublishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            published_skill = publish_skill_version(
                self.team,
                user=cast(User, request.user),
                skill_name=skill_name,
                body=payload.validated_data.get("body"),
                edits=payload.validated_data.get("edits"),
                description=payload.validated_data.get("description"),
                license=payload.validated_data.get("license"),
                compatibility=payload.validated_data.get("compatibility"),
                allowed_tools=payload.validated_data.get("allowed_tools"),
                metadata=payload.validated_data.get("metadata"),
                files=payload.validated_data.get("files"),
                file_edits=payload.validated_data.get("file_edits"),
                base_version=payload.validated_data["base_version"],
            )
        except IntegrityError as err:
            if "unique_skill_file_path" in str(err):
                raise serializers.ValidationError({"files": "Duplicate file paths are not allowed."}, code="unique")
            raise
        except LLMSkillNotFoundError:
            return self._skill_not_found_response(skill_name)
        except LLMSkillVersionConflictError as err:
            return Response(
                {
                    "detail": "The skill changed since you opened it. Reload the latest version and try again.",
                    "current_version": err.current_version,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except LLMSkillVersionLimitError as err:
            return Response(
                {
                    "detail": (
                        f"Skill has reached the maximum of {err.max_version} versions. "
                        "Archive and recreate the skill to continue publishing."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except LLMSkillEditError as err:
            error_body: dict[str, Any] = {"detail": err.message}
            if err.edit_index is not None:
                error_body["edit_index"] = err.edit_index
            if err.file_path is not None:
                error_body["file_path"] = err.file_path
            return Response(error_body, status=status.HTTP_400_BAD_REQUEST)

        report_user_action(
            cast(User, request.user),
            "llma skill version published",
            {
                "skill_id": str(published_skill.id),
                "skill_name": published_skill.name,
                "skill_version": published_skill.version,
                "base_version": payload.validated_data["base_version"],
            },
            team=self.team,
            request=request,
        )
        return Response(self._serialize_skill(published_skill))

    @extend_schema(parameters=[LLMSkillResolveQuerySerializer], responses={200: LLMSkillResolveResponseSerializer})
    @action(
        methods=["GET"],
        detail=False,
        url_path=r"resolve/name/(?P<skill_name>[^/]+)",
        required_scopes=["llm_skill:read"],
    )
    @llma_track_latency("llma_skills_resolve_by_name")
    @monitor(feature=None, endpoint="llma_skills_resolve_by_name", method="GET")
    def resolve_by_name(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        query_params = self._get_resolve_query_params(request)
        version = cast(int | None, query_params.get("version"))
        version_id = query_params.get("version_id")
        skill = get_skill_by_name_from_db(
            self.team,
            skill_name=skill_name,
            version=version,
            version_id=str(version_id) if version_id else None,
        )
        if skill is None:
            return self._skill_not_found_response(skill_name)

        limit = cast(int, query_params["limit"])
        offset = cast(int | None, query_params.get("offset"))
        before_version = cast(int | None, query_params.get("before_version"))
        versions, has_more = resolve_versions_page(
            self.team,
            skill_name=skill_name,
            limit=limit,
            offset=offset,
            before_version=before_version,
        )
        return Response(
            {
                "skill": self._serialize_skill(skill),
                "versions": self._serialize_version_summaries(versions),
                "has_more": has_more,
            }
        )

    @extend_schema(request=None, responses={204: None})
    @action(
        methods=["POST"],
        detail=False,
        url_path=r"name/(?P<skill_name>[^/]+)/archive",
        required_scopes=["llm_skill:write"],
    )
    @llma_track_latency("llma_skills_archive")
    @monitor(feature=None, endpoint="llma_skills_archive", method="POST")
    def archive(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        try:
            skill_versions = archive_skill(self.team, skill_name)
        except LLMSkillNotFoundError:
            return self._skill_not_found_response(skill_name)

        report_user_action(
            cast(User, request.user),
            "llma skill archived",
            {
                "skill_name": skill_name,
                "skill_versions": skill_versions,
            },
            team=self.team,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=LLMSkillDuplicateSerializer, responses={201: LLMSkillSerializer})
    @action(
        methods=["POST"],
        detail=False,
        url_path=r"name/(?P<skill_name>[^/]+)/duplicate",
        required_scopes=["llm_skill:write"],
    )
    @llma_track_latency("llma_skills_duplicate")
    @monitor(feature=None, endpoint="llma_skills_duplicate", method="POST")
    def duplicate(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        payload = LLMSkillDuplicateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        new_name = payload.validated_data["new_name"]

        try:
            new_skill = duplicate_skill(
                self.team,
                user=cast(User, request.user),
                source_name=skill_name,
                new_name=new_name,
            )
        except LLMSkillNotFoundError:
            return self._skill_not_found_response(skill_name)
        except LLMSkillDuplicateNameConflictError:
            return Response(
                {"attr": "new_name", "detail": "A skill with this name already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report_user_action(
            cast(User, request.user),
            "llma skill duplicated",
            {
                "skill_id": str(new_skill.id),
                "skill_name": new_skill.name,
                "source_skill_name": skill_name,
            },
            team=self.team,
            request=request,
        )
        return Response(self._serialize_skill(new_skill), status=status.HTTP_201_CREATED)

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
        version_params = self._get_requested_version_params(request)
        version = cast(int | None, version_params.get("version"))
        skill = get_skill_by_name_from_db(self.team, skill_name, version)
        if skill is None:
            return self._skill_not_found_response(skill_name)

        file_path = file_path.rstrip("/")
        normalized = file_path.replace("\\", "/")
        if ".." in normalized.split("/") or normalized.startswith("/"):
            return Response(
                {"detail": "Invalid file path."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
        ) as err:
            response = self._handle_skill_write_error(err, skill_name)
            if response is None:
                raise
            return response
        except LLMSkillFilePathConflictError as err:
            return Response(
                {"detail": f"File '{err.path}' already exists in skill '{skill_name}'."},
                status=status.HTTP_409_CONFLICT,
            )

        report_user_action(
            cast(User, request.user),
            "llma skill file created",
            {
                "skill_id": str(published_skill.id),
                "skill_name": published_skill.name,
                "skill_version": published_skill.version,
                "path": payload.validated_data["path"],
            },
            team=self.team,
            request=request,
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

        file_path = file_path.rstrip("/")
        normalized = file_path.replace("\\", "/")
        if ".." in normalized.split("/") or normalized.startswith("/"):
            return Response({"detail": "Invalid file path."}, status=status.HTTP_400_BAD_REQUEST)

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
        ) as err:
            response = self._handle_skill_write_error(err, skill_name)
            if response is None:
                raise
            return response
        except LLMSkillFileNotFoundError as err:
            return Response(
                {"detail": f"File '{err.path}' not found in skill '{skill_name}'."},
                status=status.HTTP_404_NOT_FOUND,
            )

        report_user_action(
            cast(User, request.user),
            "llma skill file deleted",
            {
                "skill_id": str(published_skill.id),
                "skill_name": published_skill.name,
                "skill_version": published_skill.version,
                "path": file_path,
            },
            team=self.team,
            request=request,
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
        ) as err:
            response = self._handle_skill_write_error(err, skill_name)
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

        report_user_action(
            cast(User, request.user),
            "llma skill file renamed",
            {
                "skill_id": str(published_skill.id),
                "skill_name": published_skill.name,
                "skill_version": published_skill.version,
                "old_path": payload.validated_data["old_path"],
                "new_path": payload.validated_data["new_path"],
            },
            team=self.team,
            request=request,
        )
        return Response(self._serialize_skill(published_skill))

    @extend_schema(parameters=[LLMSkillListQuerySerializer])
    @llma_track_latency("llma_skills_list")
    @monitor(feature=None, endpoint="llma_skills_list", method="GET")
    def list(self, request: Request, *args, **kwargs) -> Response:
        queryset = self.filter_queryset(self._get_list_queryset(request))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        return Response({"count": len(data), "results": data})

    @llma_track_latency("llma_skills_create")
    @monitor(feature=None, endpoint="llma_skills_create", method="POST")
    def create(self, request, *args, **kwargs):
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError as err:
            err_str = str(err)
            if any(
                constraint_name in err_str
                for constraint_name in ["unique_llm_skill_latest_per_team", "unique_llm_skill_version_per_team"]
            ):
                raise serializers.ValidationError({"name": "A skill with this name already exists."}, code="unique")
            if "unique_skill_file_path" in err_str:
                raise serializers.ValidationError({"files": "Duplicate file paths are not allowed."}, code="unique")
            raise
        return Response(self._serialize_skill(cast(LLMSkill, serializer.instance)), status=status.HTTP_201_CREATED)
