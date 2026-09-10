"""Moving a skill in and out of PostHog as a zip: export, bundle, and import."""

from typing import Any, cast

from django.http import HttpResponse

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.models import User
from posthog.permissions import posthog_feature_flag_value
from posthog.renderers import SafeJSONRenderer

from products.ai_observability.backend.api.metrics import llma_track_latency

from ..marketplace.adapters import (
    SANDBOX_SKILLS_FEATURE_FLAG,
    build_skill_bundle,
    load_skill_export,
    sandbox_skills_flag_distinct_id,
)
from ..marketplace.packaging import SkillImportError, build_skill_zip, parse_skill_zip, validate_for_export
from ..models.skills import LLMSkill
from .skill_analytics import record_skill_event, skill_analytics_props
from .skill_error_responses import skill_not_found_response, spec_problems_detail
from .skill_import import MAX_IMPORT_ZIP_BYTES, import_problems
from .skill_serializers import (
    LLMSkillBundleQuerySerializer,
    LLMSkillFetchQuerySerializer,
    LLMSkillImportSerializer,
    LLMSkillSerializer,
)
from .skill_services import (
    LLMSkillDuplicateNameConflictError,
    LLMSkillFileLimitError,
    LLMSkillFilePathConflictError,
    create_skill,
)
from .skill_view_access import SkillAccessMixin


class ZipRenderer(BaseRenderer):
    """Lets ``Accept: application/zip`` through content negotiation on the zip actions.

    DRF negotiates before the action runs, so with the JSON-only default a client that asks for the
    zip it was promised gets 406. The zip itself is a raw HttpResponse and never reaches a renderer;
    only the actions' error Responses do, and those stay JSON so the client can read them.
    """

    media_type = "application/zip"
    format = "zip"

    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: Any = None) -> bytes:
        if renderer_context is not None:
            renderer_context["response"]["Content-Type"] = "application/json"
        return SafeJSONRenderer().render(data, "application/json", renderer_context)


ZIP_ACTIONS = ("bundle", "export")
# With two renderers on an action, drf-spectacular advertises DRF's ``?format=`` override as a query
# parameter. Clients select the zip with ``Accept``; keep the generated types free of it.
FORMAT_QUERY_PARAM_EXCLUDED = OpenApiParameter(name="format", location=OpenApiParameter.QUERY, exclude=True)


# The zip endpoints. Errors stay JSON; only a success body is a zip.
class SkillTransferActionsMixin(SkillAccessMixin):
    @extend_schema(
        parameters=[LLMSkillFetchQuerySerializer, FORMAT_QUERY_PARAM_EXCLUDED],
        responses={(200, "application/zip"): OpenApiTypes.BINARY},
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<skill_name>[^/]+)/export")
    @llma_track_latency("llma_skills_export")
    @monitor(feature=None, endpoint="llma_skills_export", method="GET")
    def export(self, request: Request, skill_name: str = "", **kwargs) -> Response | HttpResponse:
        version_params = self._validated_query(LLMSkillFetchQuerySerializer, request)
        version = cast(int | None, version_params.get("version"))
        skill = self._load_skill_with_object_access(request, skill_name, version)
        if skill is None:
            return skill_not_found_response(skill_name)

        export = load_skill_export(skill)
        problems = validate_for_export(export)
        if problems:
            return Response(
                {
                    "detail": spec_problems_detail(
                        "Couldn't download this skill because it doesn't meet the Agent Skills spec.",
                        problems,
                        "Edit the skill to fix this, then try again.",
                    ),
                    "problems": problems,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        zip_bytes = build_skill_zip(export)
        response = HttpResponse(zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{skill.name}.zip"'
        return response

    @extend_schema(
        parameters=[LLMSkillBundleQuerySerializer, FORMAT_QUERY_PARAM_EXCLUDED],
        responses={(200, "application/zip"): OpenApiTypes.BINARY},
    )
    @action(methods=["GET"], detail=False, url_path="bundle", required_scopes=["llm_skill:read"])
    @llma_track_latency("llma_skills_bundle")
    @monitor(feature=None, endpoint="llma_skills_bundle", method="GET")
    def bundle(self, request: Request, **kwargs) -> Response | HttpResponse:
        """One zip of the requesting user's store skills, for unpacking into a skills directory."""
        query = LLMSkillBundleQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        user = cast(User, request.user)
        flag_value = posthog_feature_flag_value(
            SANDBOX_SKILLS_FEATURE_FLAG,
            sandbox_skills_flag_distinct_id(user),
            organization_id=self.organization.id,
            team_id=self.team.id,
        )
        # None means the flag service did not answer. A sandbox treats 404 as "not enabled", so
        # do not hand it that on an outage; 503 lets the caller tell the two apart.
        if flag_value is None:
            return Response(
                {"detail": "Feature flag evaluation is unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        # A plain 404 Response, not NotFound: @monitor counts raised exceptions as endpoint errors,
        # and every sandbox in a non-flagged project hits this path once per run.
        if not flag_value:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # Same object-level filter the list endpoint applies, so the bundle never carries a skill the
        # list would hide from this user.
        readable_skills = self.user_access_control.filter_queryset_by_access_level(
            LLMSkill.objects.filter(team=self.team), resource="llm_skill"
        )
        bundle = build_skill_bundle(
            self.team,
            user,
            readable_skills,
            content=query.validated_data["content"],
            limit=query.validated_data["limit"],
        )
        response = HttpResponse(bundle.zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="skills-bundle.zip"'
        # Counts only: names are unbounded and would blow past proxy header limits for heavy users.
        response["X-Skills-Included"] = str(len(bundle.included))
        response["X-Skills-Dropped"] = str(bundle.dropped_count)
        response["X-Skills-Skipped"] = str(bundle.skipped_count)
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

        problems = import_problems(skill_export)
        if problems:
            return Response(
                {
                    "detail": spec_problems_detail(
                        "Couldn't import this zip because it doesn't meet the Agent Skills spec.",
                        problems,
                        "Fix the skill files, then try again.",
                    ),
                    "problems": problems,
                },
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
            # nosemgrep: api-response-must-match-schema — DRF's error envelope, not a data payload
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

        props = {**skill_analytics_props(skill), "imported": True}
        record_skill_event(
            log_event="llma_skill_imported",
            action="llma skill imported",
            user=cast(User, request.user),
            team=self.team,
            request=request,
            props=props,
        )
        return Response(self._serialize_skill(skill), status=status.HTTP_201_CREATED)
