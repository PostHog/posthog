import logging
from typing import Any

from posthog.exceptions_capture import capture_exception
from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.schema_enums import ProductIntentContext, ProductKey

logger = logging.getLogger(__name__)


def record_tasks_product_intent(
    *,
    team: Team,
    user: User | None,
    context: ProductIntentContext = ProductIntentContext.TASK_CREATED,
    metadata: dict[str, Any] | None = None,
) -> None:
    if user is None or not user.is_authenticated:
        return

    try:
        ProductIntent.register(
            team=team,
            product_type=ProductKey.TASKS,
            context=context,
            user=user,
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning(
            "Failed to record Tasks product intent",
            extra={"team_id": team.id, "user_id": user.id, "context": context},
        )
        capture_exception(exc)
