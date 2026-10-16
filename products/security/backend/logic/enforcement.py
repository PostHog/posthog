import json
from typing import Any

import structlog
import posthoganalytics

from ..facade.enums import Surface

logger = structlog.get_logger(__name__)

# One flag in PostHog's own project. Its JSON payload names the surfaces where a block rule
# refuses requests, for example {"signup": true, "ai_gateway": false, "app": false}. Turning the
# flag off stops every refusal at once.
ENFORCEMENT_FLAG = "security-access-enforcement"


def _enforcement_payload() -> dict[str, Any]:
    payload = posthoganalytics.get_feature_flag_payload(
        ENFORCEMENT_FLAG,
        ENFORCEMENT_FLAG,
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload if isinstance(payload, dict) else {}


def is_enforced(surface: Surface) -> bool:
    """Whether the enforcement flag turns refusals on for this surface.

    Reads the locally polled flag definitions, so it never waits on the network. Anything other
    than a literal true, including missing definitions or an error, leaves the surface logging only.
    """
    try:
        return _enforcement_payload().get(surface.value) is True
    except Exception:
        logger.warning("security_access_enforcement_flag_unreadable", exc_info=True)
        return False
