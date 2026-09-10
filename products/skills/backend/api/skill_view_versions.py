"""Reading a skill by name, publishing a new version of it, and listing its history."""

from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.models import User

from products.ai_observability.backend.api.metrics import llma_track_latency

from ..models.skills import LLMSkill
from .skill_analytics import publish_analytics_props, record_skill_event
from .skill_error_responses import skill_not_found_response, skill_write_error_response, version_conflict_response
from .skill_serializers import (
    DEFAULT_BODY_PAGE_LENGTH,
    PUBLISH_CONTENT_FIELDS,
    LLMSkillBodyFetchQuerySerializer,
    LLMSkillPublishSerializer,
    LLMSkillResolveQuerySerializer,
    LLMSkillResolveResponseSerializer,
    LLMSkillSerializer,
)
from .skill_services import (
    LLMSkillDescriptionTooLongError,
    LLMSkillEditError,
    LLMSkillNotFoundError,
    LLMSkillOwnerNotFoundError,
    LLMSkillVersionConflictError,
    LLMSkillVersionLimitError,
    get_active_skill_queryset,
    get_skill_by_name_from_db,
    publish_skill_version,
    resolve_owner_users,
    resolve_versions_page,
    set_skill_owners,
)
from .skill_view_access import SkillAccessMixin


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


# The `name/<slug>` endpoints: fetch, publish, and resolve version history.
class SkillVersionActionsMixin(SkillAccessMixin):
    @extend_schema(
        parameters=[LLMSkillBodyFetchQuerySerializer],
        responses={200: LLMSkillSerializer},
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<skill_name>[^/]+)")
    @llma_track_latency("llma_skills_get_by_name")
    @monitor(feature=None, endpoint="llma_skills_get_by_name", method="GET")
    def get_by_name(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        version_params = self._validated_query(LLMSkillBodyFetchQuerySerializer, request)
        version = cast(int | None, version_params.get("version"))
        skill = self._load_skill_with_object_access(request, skill_name, version)

        if skill is None and _is_uuid(skill_name):
            redirect = self._redirect_to_name(request, skill_name)
            if redirect is not None:
                return redirect

        if skill is None:
            return skill_not_found_response(skill_name)

        # Cap the first page when the caller doesn't page explicitly, so body_next_offset is a
        # valid continuation offset even when the full body would be truncated in transit.
        body_length = cast(int | None, version_params.get("body_length"))
        if body_length is None:
            body_length = DEFAULT_BODY_PAGE_LENGTH

        return Response(
            self._serialize_skill(
                skill,
                body_offset=cast(int | None, version_params.get("body_offset")),
                body_length=body_length,
            )
        )

    def _redirect_to_name(self, request: Request, skill_name: str) -> Response | None:
        skill_by_id = get_active_skill_queryset(self.team).filter(id=skill_name).first()
        if skill_by_id is None:
            return None
        self.check_object_permissions(request, skill_by_id)
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

        access_error = self._guard_object_access(request, skill_name)
        if access_error is not None:
            return access_error

        payload = LLMSkillPublishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        validated_data = payload.validated_data

        # Resolve owners before publishing so a bad UUID 400s without minting a version. `owner_uuids`
        # is None when omitted (owners left untouched), [] when the caller clears them.
        owner_uuids = validated_data.get("owners")
        owner_users = self._resolve_publish_owners(owner_uuids)

        if owner_uuids is not None and all(validated_data.get(p) is None for p in PUBLISH_CONTENT_FIELDS):
            return self._replace_owners_only(skill_name, validated_data, cast(list, owner_users))

        try:
            published_skill = self._publish_version(request, skill_name, validated_data, owner_users)
        except (
            LLMSkillNotFoundError,
            LLMSkillVersionConflictError,
            LLMSkillVersionLimitError,
            LLMSkillDescriptionTooLongError,
            LLMSkillEditError,
        ) as err:
            error_response = skill_write_error_response(err, skill_name)
            if error_response is None:
                raise
            return error_response

        record_skill_event(
            log_event="llma_skill_version_published",
            action="llma skill version published",
            user=cast(User, request.user),
            team=self.team,
            request=request,
            props=publish_analytics_props(published_skill, validated_data, owners_changed=owner_uuids is not None),
        )
        return Response(self._serialize_skill(published_skill))

    def _resolve_publish_owners(self, owner_uuids: list[UUID] | None) -> list[User] | None:
        """The users the caller named as owners, or None when they left ownership alone."""
        if owner_uuids is None:
            return None
        try:
            return resolve_owner_users(self.team, [str(u) for u in owner_uuids])
        except LLMSkillOwnerNotFoundError as err:
            raise serializers.ValidationError(
                {"owners": f"User '{err.user_uuid}' is not a member of this project."},
                code="invalid_owner",
            )

    def _replace_owners_only(
        self, skill_name: str, validated_data: dict[str, Any], owner_users: list[User]
    ) -> Response:
        """Replace the skill's owners without publishing a version.

        Owners live on the logical skill, not a version row, so minting an identical version would
        rewrite version-history authorship, bump marketplace/update timestamps, and burn toward
        MAX_SKILL_VERSION for a no-op body. Same optimistic-concurrency contract as a publish when
        `base_version` is supplied: a stale value still 409s. It may be omitted (the generated PATCH
        schema marks it optional), which skips the version check — ownership isn't version-keyed, so
        the replace is still exact.
        """
        base_version = validated_data.get("base_version")
        # Lock the latest row for the check + replace (mirrors publish_skill_version): requests
        # run autocommit, so without the lock an owner update racing a publish from the same
        # base_version could pass a stale check and 200 where the contract advertises 409.
        with transaction.atomic():
            current_latest = (
                LLMSkill.objects.select_for_update()
                .filter(team=self.team, name=skill_name, deleted=False, is_latest=True)
                .order_by("-version", "-created_at", "-id")
                .first()
            )
            if current_latest is None:
                return skill_not_found_response(skill_name)
            if base_version is not None and base_version != current_latest.version:
                return version_conflict_response(current_latest.version)
            set_skill_owners(self.team, skill_name, owner_users)
        refreshed = get_skill_by_name_from_db(self.team, skill_name=skill_name)
        return Response(self._serialize_skill(cast(LLMSkill, refreshed)))

    def _publish_version(
        self,
        request: Request,
        skill_name: str,
        validated_data: dict[str, Any],
        owner_users: list[User] | None,
    ) -> LLMSkill:
        """Publish a new version, and replace owners in the same transaction when asked to.

        If setting owners fails, the published version rolls back with it — otherwise the new
        body/files would be live while ownership stayed stale, and a retry with the original
        base_version would 409.
        """
        try:
            with transaction.atomic():
                published_skill = publish_skill_version(
                    self.team,
                    user=cast(User, request.user),
                    skill_name=skill_name,
                    body=validated_data.get("body"),
                    edits=validated_data.get("edits"),
                    description=validated_data.get("description"),
                    license=validated_data.get("license"),
                    compatibility=validated_data.get("compatibility"),
                    allowed_tools=validated_data.get("allowed_tools"),
                    metadata=validated_data.get("metadata"),
                    files=validated_data.get("files"),
                    file_edits=validated_data.get("file_edits"),
                    base_version=validated_data["base_version"],
                    version_description=validated_data.get("version_description"),
                )
                # Owners are keyed on the logical skill, so this runs only when the caller passed
                # `owners` — a plain body edit never touches ownership.
                if owner_users is not None:
                    set_skill_owners(self.team, skill_name, owner_users)
        except IntegrityError as err:
            if "unique_skill_file_path" in str(err):
                raise serializers.ValidationError({"files": "Duplicate file paths are not allowed."}, code="unique")
            raise
        return published_skill

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

        query_params = self._validated_query(LLMSkillResolveQuerySerializer, request)
        version = cast(int | None, query_params.get("version"))
        version_id = query_params.get("version_id")
        skill = self._load_skill_with_object_access(
            request,
            skill_name,
            version,
            str(version_id) if version_id else None,
        )
        if skill is None:
            return skill_not_found_response(skill_name)

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
        # nosemgrep: api-response-must-match-schema — these are exactly LLMSkillResolveResponseSerializer's fields
        return Response(
            {
                "skill": self._serialize_skill(skill),
                "versions": self._serialize_version_summaries(versions),
                "has_more": has_more,
            }
        )
