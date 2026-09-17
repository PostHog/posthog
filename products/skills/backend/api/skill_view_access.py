"""What a caller may reach, and how a skill is serialized back to them.

Every skill endpoint mixin builds on ``SkillAccessMixin``: the object-level check the shared
``name/<slug>`` URLs need, the web-auth gate the write endpoints need, and the two serialization
helpers whose context has to match across endpoints.
"""

from difflib import get_close_matches
from typing import TYPE_CHECKING, Any, cast

from django.db.models import QuerySet

from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import (
    JwtAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
)
from posthog.models import Organization, Team

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..models.skills import LLMSkill
from .skill_serializers import LLMSkillSerializer, LLMSkillVersionSummarySerializer
from .skill_services import get_active_skill_queryset, get_skill_by_name_from_db

if TYPE_CHECKING:

    class _SkillViewBase:
        """What LLMSkillViewSet supplies to the endpoint mixins.

        Read-only declarations, so the concrete viewset's own properties stay compatible with them.
        """

        @property
        def team(self) -> Team: ...
        @property
        def organization(self) -> Organization: ...
        @property
        def user_access_control(self) -> UserAccessControl: ...
        def check_object_permissions(self, request: Request, obj: Any) -> None: ...
        def get_serializer_context(self) -> dict[str, Any]: ...

else:
    _SkillViewBase = object


# A 404 offers a few near-miss names, not a listing: `skill-list` is still the way to browse.
MAX_SKILL_NAME_SUGGESTIONS = 3
SKILL_NAME_SUGGESTION_CUTOFF = 0.6
# Ceiling on the names one miss compares against, so a large store cannot make a 404 expensive.
MAX_SKILL_NAME_MATCH_CANDIDATES = 500


# Keep this class and every endpoint mixin free of a class docstring. drf-spectacular resolves the
# viewset's docstring through its MRO, so a docstring here becomes the published OpenAPI description
# of every skill endpoint at once. The module docstring carries the description instead.
class SkillAccessMixin(_SkillViewBase):
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

    def _load_skill_with_object_access(
        self,
        request: Request,
        skill_name: str,
        version: int | None = None,
        version_id: str | None = None,
    ) -> LLMSkill | None:
        # has_permission passes anyone with a grant on any one skill, so the loaded row is checked here.
        skill = get_skill_by_name_from_db(self.team, skill_name, version, version_id)
        if skill is not None:
            self.check_object_permissions(request, skill)
        return skill

    def _guard_object_access(self, request: Request, skill_name: str) -> Response | None:
        if self._load_skill_with_object_access(request, skill_name) is None:
            return self._skill_not_found_response(skill_name)
        return None

    def _visible_skills_queryset(self) -> QuerySet[LLMSkill]:
        """Every active skill row this caller may read. `list` and every by-name read share it, so
        a name the list returned can never be denied by a read as if it did not exist."""
        return self.user_access_control.filter_queryset_by_access_level(
            get_active_skill_queryset(self.team), resource="llm_skill"
        )

    def _skill_not_found_response(self, skill_name: str, version: int | None = None) -> Response:
        """A 404 that answers from the same rows `list` returns.

        An agent that lists a skill and then cannot read it concludes the store is inconsistent
        and abandons the skill, so a miss has to say which of the two lookups it is: an unknown
        name (near-miss names the caller can actually read) or a known name at an absent version
        (the versions it does hold).
        """
        visible = self._visible_skills_queryset()
        if version is not None:
            available_versions = list(
                visible.filter(name=skill_name).order_by("version").values_list("version", flat=True)
            )
            if available_versions:
                return Response(
                    {
                        "detail": (
                            f"Skill with name '{skill_name}' has no version {version}. "
                            f"Available versions: {', '.join(str(v) for v in available_versions)}."
                        ),
                        "type": "skill_version_not_found",
                        "skill_name": skill_name,
                        "available_versions": available_versions,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        suggestions = get_close_matches(
            skill_name,
            visible.filter(is_latest=True).values_list("name", flat=True)[:MAX_SKILL_NAME_MATCH_CANDIDATES],
            n=MAX_SKILL_NAME_SUGGESTIONS,
            cutoff=SKILL_NAME_SUGGESTION_CUTOFF,
        )
        detail = f"Skill with name '{skill_name}' not found."
        if suggestions:
            detail += " Did you mean " + ", ".join(f"'{name}'" for name in suggestions) + "?"
        return Response(
            {
                "detail": detail,
                "type": "skill_not_found",
                "skill_name": skill_name,
                "suggestions": suggestions,
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    def _serialize_skill(
        self, skill: LLMSkill, *, body_offset: int | None = None, body_length: int | None = None
    ) -> dict[str, Any]:
        context = self.get_serializer_context()
        if body_offset is not None or body_length is not None:
            context = {**context, "body_offset": body_offset, "body_length": body_length}
        return cast(dict[str, Any], LLMSkillSerializer(skill, context=context).data)

    def _serialize_version_summaries(self, skills: list[LLMSkill]) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], LLMSkillVersionSummarySerializer(skills, many=True).data)

    def _validated_query(self, serializer_class: type[serializers.Serializer], request: Request) -> dict[str, Any]:
        """The request's query params, validated by `serializer_class`. 400s on a bad one."""
        serializer = serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return cast(dict[str, Any], serializer.validated_data)
