"""The whole-skill operations: archive it, duplicate it, rename it."""

from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.models import User

from products.ai_observability.backend.api.metrics import llma_track_latency

from .skill_analytics import record_skill_event, skill_analytics_props
from .skill_error_responses import skill_not_found_response
from .skill_serializers import LLMSkillDuplicateSerializer, LLMSkillRenameSerializer, LLMSkillSerializer
from .skill_services import (
    LLMSkillDescriptionTooLongError,
    LLMSkillDuplicateNameConflictError,
    LLMSkillNotFoundError,
    LLMSkillRenameNotAllowedError,
    archive_skill,
    duplicate_skill,
    rename_skill,
)
from .skill_view_access import SkillAccessMixin


# Endpoints that act on a skill as a whole rather than on one version of it.
class SkillLifecycleActionsMixin(SkillAccessMixin):
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

        access_error = self._guard_object_access(request, skill_name)
        if access_error is not None:
            return access_error

        try:
            skill_versions = archive_skill(self.team, skill_name)
        except LLMSkillNotFoundError:
            return skill_not_found_response(skill_name)

        props = {
            "skill_name": skill_name,
            "skill_versions": skill_versions,
            "skill_version_count": len(skill_versions),
            "skill_latest_version": max(skill_versions) if skill_versions else None,
        }
        record_skill_event(
            log_event="llma_skill_archived",
            action="llma skill archived",
            user=cast(User, request.user),
            team=self.team,
            request=request,
            props=props,
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

        access_error = self._guard_object_access(request, skill_name)
        if access_error is not None:
            return access_error

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
            return skill_not_found_response(skill_name)
        except LLMSkillDuplicateNameConflictError:
            # nosemgrep: api-response-must-match-schema — DRF's error envelope, not a data payload
            return Response(
                {"attr": "new_name", "detail": "A skill with this name already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except LLMSkillDescriptionTooLongError as err:
            return Response(
                {
                    "detail": (
                        f"Shorten the source skill description to {err.max_length} characters before duplicating it."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        props = {
            **skill_analytics_props(new_skill),
            "source_skill_name": skill_name,
        }
        record_skill_event(
            log_event="llma_skill_duplicated",
            action="llma skill duplicated",
            user=cast(User, request.user),
            team=self.team,
            request=request,
            props=props,
        )
        return Response(self._serialize_skill(new_skill), status=status.HTTP_201_CREATED)

    @extend_schema(request=LLMSkillRenameSerializer, responses={200: LLMSkillSerializer})
    @action(
        methods=["POST"],
        detail=False,
        url_path=r"name/(?P<skill_name>[^/]+)/rename",
        required_scopes=["llm_skill:write"],
    )
    @llma_track_latency("llma_skills_rename")
    @monitor(feature=None, endpoint="llma_skills_rename", method="POST")
    def rename(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        access_error = self._guard_object_access(request, skill_name)
        if access_error is not None:
            return access_error

        payload = LLMSkillRenameSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        new_name = payload.validated_data["new_name"]

        try:
            renamed_skill = rename_skill(self.team, skill_name=skill_name, new_name=new_name)
        except LLMSkillNotFoundError:
            return skill_not_found_response(skill_name)
        except LLMSkillDuplicateNameConflictError:
            raise serializers.ValidationError(
                {"new_name": "A skill with this name already exists."},
                code="unique",
            )
        except LLMSkillRenameNotAllowedError as err:
            raise serializers.ValidationError(
                {
                    "new_name": (
                        f"Names starting with '{err.prefix}' keep product settings under the skill name, "
                        "so a skill can't be renamed into or out of them. Duplicate the skill instead."
                    )
                },
                code="reserved_prefix",
            )

        props = {
            **skill_analytics_props(renamed_skill),
            "previous_skill_name": skill_name,
        }
        record_skill_event(
            log_event="llma_skill_renamed",
            action="llma skill renamed",
            user=cast(User, request.user),
            team=self.team,
            request=request,
            props=props,
        )
        return Response(self._serialize_skill(renamed_skill))
