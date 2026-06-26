from typing import TYPE_CHECKING

import structlog
import posthoganalytics
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from products.replay_vision.backend.models.replay_scanner import ReplayScanner

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

REPLAY_VISION_FEATURE_FLAG = "replay-vision"
# Gates the "and then…" VisionAction sub-feature, separate from product access above.
REPLAY_VISION_ACTIONS_FEATURE_FLAG = "replay-vision-actions"


def _vision_flag_enabled(flag_key: str, user: "User", team: "Team") -> bool:
    distinct_id = user.distinct_id or str(user.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)
    try:
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
    except Exception:
        # The eval runs per request against the remote flag backend; a transient failure
        # must not hard-gate the product. Treat it as "unknown" and let the caller decide.
        logger.exception("replay_vision_flag_eval_failed", flag_key=flag_key, team_id=team.id)
        return False


def _team_owns_vision_scanners(team: "Team") -> bool:
    return ReplayScanner.objects.filter(team_id=team.id).exists()


def is_replay_vision_enabled(user: "User", team: "Team") -> bool:
    if _vision_flag_enabled(REPLAY_VISION_FEATURE_FLAG, user, team):
        return True
    # Fail open for teams that already own scanners. The per-request remote flag eval can
    # come back falsy from a transient error or a frontend/backend gating mismatch (the
    # frontend bootstraps the flag client-side, the backend re-evaluates it live), and a
    # team that demonstrably has scanners has already been granted access — a 404 here
    # empties the scanner list and blocks the editor, breaking the whole product for them.
    return _team_owns_vision_scanners(team)


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
