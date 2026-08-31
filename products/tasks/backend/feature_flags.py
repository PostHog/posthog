import logging

from django.conf import settings

import posthoganalytics

from posthog.utils import get_instance_region

from products.tasks.backend.constants import (
    AGENT_OTEL_TELEMETRY_STATE_KEY,
    AGENT_RUN_OTEL_TELEMETRY_FEATURE_FLAG,
    DEV_STACK_IMAGE_BAKE_FEATURE_FLAG,
    WORKFLOW_DISPATCH_ASYNC_FEATURE_FLAG,
    WORKFLOW_DISPATCH_RESTART_FEATURE_FLAG,
    WORKFLOW_DISPATCH_SHADOW_FEATURE_FLAG,
    get_required_model_flag,
)

logger = logging.getLogger(__name__)

NATIVE_STEERING_SIGNALS_FEATURE_FLAG = "tasks-native-steering-signals"
NATIVE_STEERING_SIGNALS_DISTINCT_ID = "tasks-native-steering-signals"

DEV_STACK_IMAGE_BAKE_DISTINCT_ID = "tasks-dev-stack-image-bake"
WORKFLOW_DISPATCH_SHADOW_DISTINCT_ID = "tasks-workflow-dispatch-shadow"


def is_workflow_dispatch_shadow_enabled() -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                WORKFLOW_DISPATCH_SHADOW_FEATURE_FLAG,
                distinct_id=WORKFLOW_DISPATCH_SHADOW_DISTINCT_ID,
                person_properties={"region": get_instance_region() or "DEV"},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("workflow_dispatch_shadow_flag_check_failed")
        return False


def _is_workflow_dispatch_org_flag_enabled(flag: str, organization_id: str, distinct_id: str) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("workflow_dispatch_org_flag_check_failed", extra={"flag": flag})
        return False


def is_workflow_dispatch_async_enabled(organization_id: str, distinct_id: str) -> bool:
    return _is_workflow_dispatch_org_flag_enabled(WORKFLOW_DISPATCH_ASYNC_FEATURE_FLAG, organization_id, distinct_id)


def is_workflow_dispatch_restart_enabled(organization_id: str, distinct_id: str) -> bool:
    return _is_workflow_dispatch_org_flag_enabled(WORKFLOW_DISPATCH_RESTART_FEATURE_FLAG, organization_id, distinct_id)


def is_dev_stack_image_bake_enabled() -> bool:
    """Gates the nightly prebaked dev-stack image bake (a paid Modal VM run per tick).

    The bake publishes into the region's own Modal workspace, so the flag is evaluated
    with the deployment region as a person property — release conditions can enable one
    region at a time (`region = US` first). Fail-closed: a flag-service error must not
    start a bake, and local dev is excluded outright — use `manage.py
    bake_dev_stack_image` to bake manually."""
    # Explicit rather than inherited from SDK state: self-capture re-enables
    # posthoganalytics in local dev, so without this guard a locally seeded flag could
    # start paid Modal bakes from a laptop.
    if settings.DEBUG:
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                DEV_STACK_IMAGE_BAKE_FEATURE_FLAG,
                distinct_id=DEV_STACK_IMAGE_BAKE_DISTINCT_ID,
                # Same region vocabulary as other region-conditioned flags: US / EU / DEV.
                person_properties={"region": get_instance_region() or "DEV"},
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


def get_model_access_error(model: str | None, *, distinct_id: str | None) -> str | None:
    """Reject a gated model the caller isn't entitled to; `None` when the selection is allowed.

    Fail-closed on purpose. Only a model in `MODEL_ACCESS_FLAGS` reaches an evaluation at all,
    so an evaluation outage withholds a preview model from everyone rather than opening it to
    everyone — the opposite trade to the telemetry flags above, because this one decides spend.
    """
    flag_key = get_required_model_flag(model)
    if flag_key is None:
        return None

    # The analytics SDK is disabled in local dev, where every flag reads as off.
    if settings.DEBUG:
        return None

    not_available = f"'{model}' is not available for your account."
    if not distinct_id:
        return not_available

    try:
        enabled = posthoganalytics.feature_enabled(
            flag_key,
            distinct_id=distinct_id,
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception("model_access_flag_check_failed", extra={"flag": flag_key, "model": model})
        return not_available

    return None if enabled else not_available


def agent_otel_telemetry_enabled_for_state(state: dict | None) -> bool:
    """Per-run telemetry decision, read from the flag value stamped into run state at dispatch.

    DEBUG bypasses the flag: the analytics SDK is disabled in local dev, where the
    telemetry env settings / mirror settings are themselves the opt-in.
    """
    if settings.DEBUG:
        return True
    return (state or {}).get(AGENT_OTEL_TELEMETRY_STATE_KEY) is True
