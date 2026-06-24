from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError
from django.db.models import Q, QuerySet
from django.http import HttpResponse

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
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
from posthog.permissions import AccessControlPermission
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.ai_observability.backend.api.metrics import llma_track_latency

from ..marketplace.adapters import MARKETPLACE_NAME, PLUGIN_NAME, load_skill_export
from ..marketplace.credentials import (
    build_codex_install_command,
    build_install_command,
    get_marketplace_credential,
    issue_marketplace_credential,
    marketplace_credential_label,
    marketplace_repo_url,
)
from ..marketplace.packaging import SkillImportError, build_skill_zip, parse_skill_zip, validate_for_export
from ..models.skills import LLMSkill, LLMSkillFile
from .skill_serializers import (
    MAX_SKILL_FILE_BYTES,
    LLMSkillCreateSerializer,
    LLMSkillDuplicateSerializer,
    LLMSkillFetchQuerySerializer,
    LLMSkillFileCreateSerializer,
    LLMSkillFileDeleteQuerySerializer,
    LLMSkillFileRenameSerializer,
    LLMSkillFileSerializer,
    LLMSkillImportSerializer,
    LLMSkillListQuerySerializer,
    LLMSkillListSerializer,
    LLMSkillMarketplaceCommandSerializer,
    LLMSkillMarketplaceIssueSerializer,
    LLMSkillPublishSerializer,
    LLMSkillResolveQuerySerializer,
    LLMSkillResolveResponseSerializer,
    LLMSkillSerializer,
    LLMSkillVersionSummarySerializer,
    validate_allowed_tool,
    validate_skill_body_size,
    validate_skill_file_path,
    validate_skill_name_value,
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
    create_skill,
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

logger = structlog.get_logger(__name__)

# Generous ceiling for an uploaded skill zip — per-skill content (body, 50 files × 1 MB) is
# already bounded by create_skill, this just caps the upload before we read it into memory.
MAX_IMPORT_ZIP_BYTES = 10_000_000


def _file_extension(path: str) -> str:
    return path.rsplit(".", 1)[1].lower() if "." in path else ""


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _skill_analytics_props(skill: LLMSkill) -> dict[str, Any]:
    """Properties shared by every skill report_user_action event.

    These power the internal LLMA skills adoption/usage dashboards — keep stable
    and additive (renaming a key here will rename it on every dashboard).
    """
    file_count = skill.files.count() if skill.pk else 0
    body = skill.body or ""
    description = skill.description or ""
    allowed_tools = skill.allowed_tools or []
    return {
        "skill_id": str(skill.id),
        "skill_name": skill.name,
        "skill_version": skill.version,
        "skill_is_latest": skill.is_latest,
        "skill_body_length": len(body),
        "skill_description_length": len(description),
        "skill_file_count": file_count,
        "skill_has_files": file_count > 0,
        "skill_has_license": bool(skill.license),
        "skill_has_compatibility": bool(skill.compatibility),
        "skill_has_allowed_tools": bool(allowed_tools),
        "skill_allowed_tools_count": len(allowed_tools),
    }


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
    permission_classes = [AccessControlPermission]

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
        # marketplace_command (GET, read state) and issue_marketplace_command (POST, mint/rotate the
        # credential) share a URL via @marketplace_command.mapping.post. Resolve per-method.
        if view.action in ["marketplace_command", "issue_marketplace_command"]:
            return ["llm_skill:write"] if request.method == "POST" else ["llm_skill:read"]
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

        # Presence of the param — even as an empty string — is a filter: `?category=` returns only
        # uncategorized skills, `?category=scout` only scouts. Omitting it returns every category.
        if "category" in request.query_params:
            queryset = queryset.filter(category=params.get("category") or "")

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

        props = _skill_analytics_props(instance)
        logger.info(
            "llma_skill_created",
            team_id=self.team.id,
            user_id=cast(User, self.request.user).id,
            **props,
        )
        report_user_action(
            cast(User, self.request.user),
            "llma skill created",
            props,
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

        if skill is None and _is_uuid(skill_name):
            redirect = self._redirect_to_name(request, skill_name)
            if redirect is not None:
                return redirect

        if skill is None:
            return self._skill_not_found_response(skill_name)

        return Response(self._serialize_skill(skill))

    def _redirect_to_name(self, request: Request, skill_name: str) -> Response | None:
        skill_by_id = get_active_skill_queryset(self.team).filter(id=skill_name).first()
        if skill_by_id is None:
            return None
        # Use a relative path (no build_absolute_uri) to avoid embedding the
        # Host header in the Location value — prevents host-header open-redirect.
        redirect_url = request.get_full_path().replace(skill_name, skill_by_id.name, 1)
        response = Response(status=status.HTTP_302_FOUND)
        response["Location"] = redirect_url
        return response

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

        edits_value = payload.validated_data.get("edits")
        file_edits_value = payload.validated_data.get("file_edits")
        files_value = payload.validated_data.get("files")
        props = {
            **_skill_analytics_props(published_skill),
            "base_version": payload.validated_data["base_version"],
            "body_changed": payload.validated_data.get("body") is not None or edits_value is not None,
            "files_replaced": files_value is not None,
            "files_replaced_count": len(files_value) if files_value is not None else 0,
            "edits_used": edits_value is not None,
            "edits_count": len(edits_value) if edits_value is not None else 0,
            "file_edits_used": file_edits_value is not None,
            "file_edits_count": len(file_edits_value) if file_edits_value is not None else 0,
            "description_changed": payload.validated_data.get("description") is not None,
            "license_changed": payload.validated_data.get("license") is not None,
            "compatibility_changed": payload.validated_data.get("compatibility") is not None,
            "allowed_tools_changed": payload.validated_data.get("allowed_tools") is not None,
            "metadata_changed": payload.validated_data.get("metadata") is not None,
        }
        logger.info(
            "llma_skill_version_published",
            team_id=self.team.id,
            user_id=cast(User, request.user).id,
            **props,
        )
        report_user_action(
            cast(User, request.user),
            "llma skill version published",
            props,
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

    @extend_schema(
        parameters=[LLMSkillFetchQuerySerializer],
        responses={(200, "application/zip"): OpenApiTypes.BINARY},
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<skill_name>[^/]+)/export")
    @llma_track_latency("llma_skills_export")
    @monitor(feature=None, endpoint="llma_skills_export", method="GET")
    def export(self, request: Request, skill_name: str = "", **kwargs) -> Response | HttpResponse:
        version_params = self._get_requested_version_params(request)
        version = cast(int | None, version_params.get("version"))
        skill = get_skill_by_name_from_db(self.team, skill_name, version)
        if skill is None:
            return self._skill_not_found_response(skill_name)

        export = load_skill_export(skill)
        problems = validate_for_export(export)
        if problems:
            return Response(
                {"detail": "Skill is not export-ready under the Agent Skills spec.", "problems": problems},
                status=status.HTTP_400_BAD_REQUEST,
            )

        zip_bytes = build_skill_zip(export)
        response = HttpResponse(zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{skill.name}.zip"'
        return response

    @extend_schema(request=LLMSkillImportSerializer, responses={201: LLMSkillSerializer})
    @action(
        methods=["POST"],
        detail=False,
        url_path="import",
        required_scopes=["llm_skill:write"],
        parser_classes=[MultiPartParser, FormParser],
    )
    @llma_track_latency("llma_skills_import")
    @monitor(feature=None, endpoint="llma_skills_import", method="POST")
    def import_skill(self, request: Request, **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "Attach the skill .zip as multipart form field 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Bound the read by bytes (read one past the cap) — upload.size is not always reliable, so
        # don't trust it as the only guard against buffering an oversized body into memory.
        raw = upload.read(MAX_IMPORT_ZIP_BYTES + 1)
        if len(raw) > MAX_IMPORT_ZIP_BYTES:
            return Response(
                {"detail": f"Zip must be {MAX_IMPORT_ZIP_BYTES} bytes or fewer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            skill_export = parse_skill_zip(raw)
        except SkillImportError as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        problems = self._import_problems(skill_export)
        if problems:
            return Response(
                {"detail": "Zip is not a valid, spec-compliant skill.", "problems": problems},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            skill = create_skill(
                self.team,
                user=cast(User, request.user),
                name=skill_export.name,
                description=skill_export.description,
                body=skill_export.body,
                license=skill_export.license,
                compatibility=skill_export.compatibility,
                allowed_tools=skill_export.allowed_tools,
                metadata=skill_export.metadata,
                files=[
                    {"path": f.path, "content": f.content, "content_type": f.content_type} for f in skill_export.files
                ],
            )
        except LLMSkillDuplicateNameConflictError:
            return Response(
                {"attr": "name", "detail": f"A skill named '{skill_export.name}' already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except LLMSkillFilePathConflictError:
            return Response({"detail": "Duplicate bundled file paths in the zip."}, status=status.HTTP_400_BAD_REQUEST)
        except LLMSkillFileLimitError as err:
            return Response(
                {"detail": f"Skill exceeds the maximum of {err.max_count} bundled files."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        props = {**_skill_analytics_props(skill), "imported": True}
        logger.info("llma_skill_imported", team_id=self.team.id, user_id=cast(User, request.user).id, **props)
        report_user_action(cast(User, request.user), "llma skill imported", props, team=self.team, request=request)
        return Response(self._serialize_skill(skill), status=status.HTTP_201_CREATED)

    def _import_problems(self, skill_export) -> list[str]:
        # The import path calls create_skill directly, so it must re-apply the same size/shape limits
        # the create/edit serializers enforce — otherwise a spec-valid zip could persist content
        # (oversized body/files, whitespace-bearing tools) the rest of the system assumes is bounded.
        # validate_for_export already covers the description (non-empty, ≤ spec limit).
        problems: list[str] = list(validate_for_export(skill_export))
        try:
            validate_skill_name_value(skill_export.name)
        except serializers.ValidationError as err:
            problems.append(f"name: {self._first_error(err)}")
        try:
            validate_skill_body_size(skill_export.body)
        except serializers.ValidationError as err:
            problems.append(f"body: {self._first_error(err)}")
        for tool in skill_export.allowed_tools:
            try:
                validate_allowed_tool(tool)
            except serializers.ValidationError as err:
                problems.append(f"allowed-tools '{tool}': {self._first_error(err)}")
        if len(skill_export.license) > 255:
            problems.append("license must be 255 characters or fewer")
        if len(skill_export.compatibility) > 500:
            problems.append("compatibility must be 500 characters or fewer")

        seen_lower: set[str] = set()
        for skill_file in skill_export.files:
            try:
                validate_skill_file_path(skill_file.path)
            except serializers.ValidationError as err:
                problems.append(f"file '{skill_file.path}': {self._first_error(err)}")
            if len(skill_file.content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
                problems.append(f"file '{skill_file.path}': content must be {MAX_SKILL_FILE_BYTES} bytes or fewer")
            lowered = skill_file.path.lower()
            if lowered in seen_lower:
                problems.append(f"file '{skill_file.path}': collides with another file (case-insensitive)")
            seen_lower.add(lowered)
        return problems

    @staticmethod
    def _first_error(err: serializers.ValidationError) -> str:
        detail = err.detail
        if isinstance(detail, list) and detail:
            return str(detail[0])
        return str(detail)

    def _marketplace_command_payload(self, request: Request, key, token: str | None, status_str: str) -> dict[str, Any]:
        """Shape the marketplace-command response from a credential (or absence of one)."""
        team_id = self.team.id

        def claude(tok: str | None) -> str:
            return build_install_command(team_id, tok, plugin_name=PLUGIN_NAME, marketplace_name=MARKETPLACE_NAME)

        def codex(tok: str | None) -> str:
            return build_codex_install_command(team_id, tok, plugin_name=PLUGIN_NAME, marketplace_name=MARKETPLACE_NAME)

        return {
            "status": status_str,
            "connected": key is not None,
            "plugin_name": PLUGIN_NAME,
            "marketplace_name": MARKETPLACE_NAME,
            "label": marketplace_credential_label(team_id),
            "repo_url": marketplace_repo_url(team_id),
            "command": claude(token) if token else None,
            "command_template": claude(None),
            "codex_command": codex(token) if token else None,
            "codex_command_template": codex(None),
            "token": token,
            "mask_value": key.mask_value if key is not None else None,
            "created_at": key.created_at if key is not None else None,
            "last_rolled_at": key.last_rolled_at if key is not None else None,
        }

    @extend_schema(responses={200: LLMSkillMarketplaceCommandSerializer})
    @action(methods=["GET"], detail=False, url_path="marketplace/install-command")
    @llma_track_latency("llma_skills_marketplace_command")
    @monitor(feature=None, endpoint="llma_skills_marketplace_command", method="GET")
    def marketplace_command(self, request: Request, **kwargs) -> Response:
        """Report whether the user already has a marketplace credential, without minting one.

        The token is unrecoverable, so an existing credential returns its mask only — the UI shows
        "already connected, existing setups keep working" and offers an explicit rotate.
        """
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        key = get_marketplace_credential(self.team, cast(User, request.user))
        payload = self._marketplace_command_payload(request, key, None, "exists" if key is not None else "absent")
        return Response(LLMSkillMarketplaceCommandSerializer(payload).data)

    @extend_schema(request=LLMSkillMarketplaceIssueSerializer, responses={200: LLMSkillMarketplaceCommandSerializer})
    @marketplace_command.mapping.post
    @llma_track_latency("llma_skills_marketplace_issue")
    @monitor(feature=None, endpoint="llma_skills_marketplace_issue", method="POST")
    def issue_marketplace_command(self, request: Request, **kwargs) -> Response:
        """Mint the user's read-only marketplace credential (or rotate it) and return the install command.

        Per-user: rotating only ever invalidates this user's own credential, never a teammate's.
        """
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        payload = LLMSkillMarketplaceIssueSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        issued = issue_marketplace_credential(
            self.team, cast(User, request.user), rotate=payload.validated_data["rotate"]
        )

        if issued.status in ("created", "rotated"):
            props = {"status": issued.status, "plugin_name": PLUGIN_NAME}
            logger.info(
                "llma_skill_marketplace_credential_issued",
                team_id=self.team.id,
                user_id=cast(User, request.user).id,
                **props,
            )
            report_user_action(
                cast(User, request.user),
                "llma skill marketplace credential issued",
                props,
                team=self.team,
                request=request,
            )

        result = self._marketplace_command_payload(request, issued.key, issued.token, issued.status)
        return Response(LLMSkillMarketplaceCommandSerializer(result).data)

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

        props = {
            "skill_name": skill_name,
            "skill_versions": skill_versions,
            "skill_version_count": len(skill_versions),
            "skill_latest_version": max(skill_versions) if skill_versions else None,
        }
        logger.info(
            "llma_skill_archived",
            team_id=self.team.id,
            user_id=cast(User, request.user).id,
            **props,
        )
        report_user_action(
            cast(User, request.user),
            "llma skill archived",
            props,
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

        props = {
            **_skill_analytics_props(new_skill),
            "source_skill_name": skill_name,
        }
        logger.info(
            "llma_skill_duplicated",
            team_id=self.team.id,
            user_id=cast(User, request.user).id,
            **props,
        )
        report_user_action(
            cast(User, request.user),
            "llma skill duplicated",
            props,
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

        path_value = payload.validated_data["path"]
        content_value = payload.validated_data["content"]
        props = {
            **_skill_analytics_props(published_skill),
            "path": path_value,
            "content_type": payload.validated_data.get("content_type", "text/plain"),
            "file_content_length": len(content_value),
            "file_extension": _file_extension(path_value),
        }
        logger.info(
            "llma_skill_file_created",
            team_id=self.team.id,
            user_id=cast(User, request.user).id,
            **props,
        )
        report_user_action(
            cast(User, request.user),
            "llma skill file created",
            props,
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

        props = {
            **_skill_analytics_props(published_skill),
            "path": file_path,
            "file_extension": _file_extension(file_path),
        }
        logger.info(
            "llma_skill_file_deleted",
            team_id=self.team.id,
            user_id=cast(User, request.user).id,
            **props,
        )
        report_user_action(
            cast(User, request.user),
            "llma skill file deleted",
            props,
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

        old_path_value = payload.validated_data["old_path"]
        new_path_value = payload.validated_data["new_path"]
        old_extension = _file_extension(old_path_value)
        new_extension = _file_extension(new_path_value)
        props = {
            **_skill_analytics_props(published_skill),
            "old_path": old_path_value,
            "new_path": new_path_value,
            "old_file_extension": old_extension,
            "new_file_extension": new_extension,
            "extension_changed": old_extension != new_extension,
        }
        logger.info(
            "llma_skill_file_renamed",
            team_id=self.team.id,
            user_id=cast(User, request.user).id,
            **props,
        )
        report_user_action(
            cast(User, request.user),
            "llma skill file renamed",
            props,
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
