import logging

from django.conf import settings

import posthoganalytics

from posthog.settings import CLOUD_DEPLOYMENT

from products.tasks.backend.constants import (
    AGENT_OTEL_TELEMETRY_STATE_KEY,
    AGENT_RUN_OTEL_TELEMETRY_FEATURE_FLAG,
    DEV_STACK_IMAGE_BAKE_FEATURE_FLAG,
)

logger = logging.getLogger(__name__)

NATIVE_STEERING_SIGNALS_FEATURE_FLAG = "tasks-native-steering-signals"
NATIVE_STEERING_SIGNALS_DISTINCT_ID = "tasks-native-steering-signals"

DEV_STACK_IMAGE_BAKE_DISTINCT_ID = "tasks-dev-stack-image-bake"


def is_dev_stack_image_bake_enabled() -> bool:
    """Gates the nightly prebaked dev-stack image bake (a paid Modal VM run per tick).

    The bake publishes into the region's own Modal workspace, so the flag is evaluated
    with the deployment region as a person property — release conditions can enable one
    region at a time (`region = US` first). Fail-closed: a flag-service error must not
    start a bake, and local dev (where the analytics SDK is disabled) always resolves
    False — use `manage.py bake_dev_stack_image` to bake manually."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                DEV_STACK_IMAGE_BAKE_FEATURE_FLAG,
                distinct_id=DEV_STACK_IMAGE_BAKE_DISTINCT_ID,
                person_properties={"region": CLOUD_DEPLOYMENT or "unknown"},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("dev_stack_image_bake_flag_check_failed")
        return False


def is_native_steering_signals_enabled() -> bool:
    if settings.DEBUG:
        return True

    try:
        return bool(
            posthoganalytics.feature_enabled(
                NATIVE_STEERING_SIGNALS_FEATURE_FLAG,
                distinct_id=NATIVE_STEERING_SIGNALS_DISTINCT_ID,
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("native_steering_signals_feature_flag_check_failed")
        return False


def is_agent_otel_telemetry_enabled(*, distinct_id: str, organization_id: str) -> bool:
    """Org-gated rollout of agent-run OTel telemetry; fail-closed when evaluation fails."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                AGENT_RUN_OTEL_TELEMETRY_FEATURE_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("agent_otel_telemetry_flag_check_failed")
        return False


def agent_otel_telemetry_enabled_for_state(state: dict | None) -> bool:
    """Per-run telemetry decision, read from the flag value stamped into run state at dispatch.

    DEBUG bypasses the flag: the analytics SDK is disabled in local dev, where the
    telemetry env settings / mirror settings are themselves the opt-in.
    """
    if settings.DEBUG:
        return True
    return (state or {}).get(AGENT_OTEL_TELEMETRY_STATE_KEY) is True
