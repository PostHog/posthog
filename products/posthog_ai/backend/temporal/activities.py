from dataclasses import dataclass

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models import Team, User

from products.posthog_ai.backend.conversation_mirror import MirrorResult, amirror_conversation

from ee.hogai.utils.feature_flags import has_conversation_task_mirror_feature_flag

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class MirrorConversationInputs:
    team_id: int
    user_id: int
    conversation_id: str


@activity.defn
async def mirror_conversation_to_task_activity(inputs: MirrorConversationInputs) -> None:
    team = await Team.objects.aget(id=inputs.team_id)
    user = await User.objects.aget(id=inputs.user_id)
    if not await sync_to_async(has_conversation_task_mirror_feature_flag)(team, user):
        result = MirrorResult(skipped_reason="flag", task_id=None, run_id=None, appended_frames=0)
    else:
        result = await amirror_conversation(inputs.conversation_id, inputs.team_id, inputs.user_id)
    logger.info(
        "conversation_mirror.activity_done",
        conversation_id=inputs.conversation_id,
        skipped_reason=result.skipped_reason,
        appended_frames=result.appended_frames,
    )
