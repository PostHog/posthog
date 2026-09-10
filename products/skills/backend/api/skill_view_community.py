"""Publishing a skill to the public community marketplace."""

from typing import cast

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.models import User

from products.ai_observability.backend.api.metrics import llma_track_latency

from .community_publish_services import (
    CommunitySkillPublishError,
    CommunitySkillPublishNotConfiguredError,
    CommunitySkillPublishValidationError,
    publish_skill_to_community,
    publishable_tags,
)
from .skill_analytics import record_skill_event, skill_analytics_props
from .skill_error_responses import skill_not_found_response
from .skill_serializers import CommunitySkillPublishResultSerializer, LLMSkillPublishToCommunitySerializer
from .skill_view_access import SkillAccessMixin

logger = structlog.get_logger(__name__)


# Reachable only through CommunityPublishOwnerPermission and the publish throttles, which live in
# skill_permissions and skill_throttles.
class SkillCommunityPublishMixin(SkillAccessMixin):
    @extend_schema(request=LLMSkillPublishToCommunitySerializer, responses={201: CommunitySkillPublishResultSerializer})
    @action(
        methods=["POST"],
        detail=False,
        url_path=r"name/(?P<skill_name>[^/]+)/publish-community",
        required_scopes=["llm_skill:write"],
    )
    @llma_track_latency("llma_skills_publish_community")
    @monitor(feature=None, endpoint="llma_skills_publish_community", method="POST")
    def publish_to_community(self, request: Request, skill_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        skill = self._load_skill_with_object_access(request, skill_name)
        if skill is None:
            return skill_not_found_response(skill_name)

        payload = LLMSkillPublishToCommunitySerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        files = [{"path": f.path, "content": f.content, "content_type": f.content_type} for f in skill.files.all()]
        supplied_tags = payload.validated_data.get("tags")
        # An explicit empty list means "publish with no tags", so fall back to the skill's own tags
        # only when the caller omitted the field. Those are unvalidated metadata, unlike the ones the
        # serializer checked, so they go through publishable_tags first.
        if supplied_tags is None:
            supplied_tags = publishable_tags((skill.metadata or {}).get("tags"))
        # The LLMSkill name is the kebab slug; default the community display name to a title-cased form.
        display_name = payload.validated_data.get("display_name") or skill.name.replace("-", " ").title()

        try:
            result = publish_skill_to_community(
                slug=skill.name,
                # Scopes the publish branch to this team, so one team cannot rewrite another team's
                # open pull request for the same slug.
                publisher_id=str(self.team.uuid),
                name=display_name,
                description=skill.description,
                body=skill.body,
                files=files or None,
                tags=supplied_tags,
                allowed_tools=skill.allowed_tools or [],
                license=skill.license or "",
                compatibility=skill.compatibility or "",
                author_handle=payload.validated_data.get("author_handle", ""),
                metadata=skill.metadata,
            )
        except CommunitySkillPublishNotConfiguredError:
            # The fail-safe is otherwise silent, so an instance that meant to have publishing on
            # looks like one that never configured it until somebody reports the toast.
            logger.warning(
                "llma_skill_publish_to_community_not_configured",
                team_id=self.team.id,
                user_id=cast(User, request.user).id,
                skill_name=skill.name,
            )
            return Response(
                {"detail": "Publishing to the community is not available on this instance."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except CommunitySkillPublishValidationError as err:
            # Nothing reached GitHub, and republishing the same skill fails the same way — the
            # publisher has to edit it. That is a 400, not the 502 an unreachable GitHub gets.
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        except CommunitySkillPublishError as err:
            # The client sees the reason once; without this the server keeps no record of a publish
            # that failed against GitHub.
            logger.warning(
                "llma_skill_publish_to_community_failed",
                team_id=self.team.id,
                user_id=cast(User, request.user).id,
                skill_name=skill.name,
                error=str(err),
            )
            return Response({"detail": str(err)}, status=status.HTTP_502_BAD_GATEWAY)

        props = {**skill_analytics_props(skill), "community_pr_number": result["pr_number"]}
        record_skill_event(
            log_event="llma_skill_published_to_community",
            action="llma skill published to community",
            user=cast(User, request.user),
            team=self.team,
            request=request,
            props=props,
        )
        return Response(result, status=status.HTTP_201_CREATED)
