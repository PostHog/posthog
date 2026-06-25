"""Feature-flag checks for the Slack app backend.

One module for all Slack-app flag checks so rollouts are easy to find and
audit. Every check here is fail-closed: a flaky ``posthoganalytics.feature_enabled``
call must not silently enable a feature for everyone.
"""

from __future__ import annotations

import structlog
import posthoganalytics

from posthog.models.integration import Integration
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)


SLACK_APP_HOME_FLAG = "slack-app-home"


def is_slack_app_home_enabled(integration: Integration, *, region: str | None = None) -> bool:
    """Return True when the ``slack-app-home`` flag is on for this workspace.

    The flag controls the App Home tab surface and the AI-settings resolver
    that feeds Slack-triggered task runs. Keyed on Slack workspace id +
    PostHog org so the same flag rule can target either dimension.

    ``region`` overrides the auto-detected instance region — useful in dev
    environments where ``get_instance_region()`` returns ``None``. The
    default fallback is ``"dev"`` (not ``"unknown"``), so a flag rule
    targeting ``region == "dev"`` opts local environments in without
    leaking to prod.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_HOME_FLAG,
                f"slack_workspace:{integration.integration_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties={"region": region or get_instance_region() or "dev"},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(
            "slack_app_home_feature_flag_check_failed",
            integration_id=integration.id,
        )
        return False
