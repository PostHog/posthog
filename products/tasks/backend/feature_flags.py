import logging

from django.conf import settings

import posthoganalytics

logger = logging.getLogger(__name__)

NATIVE_STEERING_SIGNALS_FEATURE_FLAG = "tasks-native-steering-signals"
NATIVE_STEERING_SIGNALS_DISTINCT_ID = "tasks-native-steering-signals"


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
