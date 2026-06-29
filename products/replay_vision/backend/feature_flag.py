from typing import TYPE_CHECKING

import posthoganalytics
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User

REPLAY_VISION_FEATURE_FLAG = "replay-vision"
# Gates the "and then…" VisionAction sub-feature, separate from product access above.
REPLAY_VISION_ACTIONS_FEATURE_FLAG = "replay-vision-actions"


def _vision_flag_enabled(flag_key: str, user: "User", team: "Team") -> bool:
    distinct_id = user.distinct_id or str(user.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)
    return bool(
        posthoganalytics.feature_enabled(
            flag_key,
            distinct_id,
            groups={"organization": organization_id, "project": project_id},
            group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def is_replay_vision_enabled(user: "User", team: "Team") -> bool:
    return _vision_flag_enabled(REPLAY_VISION_FEATURE_FLAG, user, team)


def is_replay_vision_actions_enabled(user: "User", team: "Team") -> bool:
    return _vision_flag_enabled(REPLAY_VISION_ACTIONS_FEATURE_FLAG, user, team)


class ReplayVisionEnabledPermission(BasePermission):
    """Hide Vision endpoints behind the `replay-vision` flag — 404 (not 403) when off."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not is_replay_vision_enabled(request.user, view.team):  # type: ignore[arg-type, attr-defined]
            raise NotFound()
        return True


class ReplayVisionActionsEnabledPermission(BasePermission):
    """Hide Vision *action* endpoints behind the `replay-vision-actions` flag — 404 (not 403) when off."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not is_replay_vision_actions_enabled(request.user, view.team):  # type: ignore[arg-type, attr-defined]
            raise NotFound()
        return True
