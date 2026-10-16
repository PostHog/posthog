import structlog

from posthog.models import Team, User
from posthog.permissions import posthog_feature_flag_enabled

logger = structlog.get_logger(__name__)

SLACK_DEV_MCP_UI_FLAG = "mcp-slack-dev"


def slack_dev_mcp_ui_enabled(*, user: User, team: Team) -> bool:
    try:
        return posthog_feature_flag_enabled(
            SLACK_DEV_MCP_UI_FLAG,
            str(user.distinct_id),
            organization_id=team.organization_id,
            team_id=team.id,
            person_properties={"email": user.email} if user.email else {},
            # Local evaluation only: both call sites sit in a request path, and the SDK's remote
            # fallback blocks for up to its request timeout. The email-suffix rollout still
            # resolves locally because `person_properties` supplies the address.
            only_evaluate_locally=True,
        )
    except Exception:
        logger.warning("mcp_store.slack_dev_flag_check_failed", exc_info=True)
        return False
