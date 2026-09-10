"""What a caller may reach, and how a skill is serialized back to them.

Every skill endpoint mixin builds on ``SkillAccessMixin``: the object-level check the shared
``name/<slug>`` URLs need, the web-auth gate the write endpoints need, and the two serialization
helpers whose context has to match across endpoints.
"""

from typing import TYPE_CHECKING, Any, cast

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
from .skill_error_responses import skill_not_found_response
from .skill_serializers import LLMSkillSerializer, LLMSkillVersionSummarySerializer
from .skill_services import get_skill_by_name_from_db

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
            return skill_not_found_response(skill_name)
        return None

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
