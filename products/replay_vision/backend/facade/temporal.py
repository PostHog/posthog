"""The replay vision Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from django.conf import settings

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.replay_vision.backend.temporal import (
    ACTIVITIES as REPLAY_VISION_ACTIVITIES,
    WORKFLOWS as REPLAY_VISION_WORKFLOWS,
)
from products.replay_vision.backend.temporal.estimates import create_replay_vision_estimates_schedule
from products.replay_vision.backend.temporal.gemini_cleanup_sweep import (
    create_replay_vision_gemini_cleanup_sweep_schedule,
)
from products.replay_vision.backend.temporal.highlight_rebuild import create_replay_vision_highlight_rebuild_schedule
from products.replay_vision.backend.temporal.learned_rules import create_replay_vision_learned_rules_schedule
from products.replay_vision.backend.temporal.read_meter import create_replay_vision_read_meter_schedule
from products.replay_vision.backend.temporal.reconciler import create_replay_vision_reconciler_schedule
from products.replay_vision.backend.temporal.vision_alerts.schedule import create_vision_alert_check_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="REPLAY_VISION_TASK_QUEUE",
            workflows=tuple(REPLAY_VISION_WORKFLOWS),
            activities=tuple(REPLAY_VISION_ACTIVITIES),
        ),
    ),
    schedules=(
        create_replay_vision_reconciler_schedule,
        create_replay_vision_estimates_schedule,
        create_replay_vision_learned_rules_schedule,
        create_vision_alert_check_schedule,
        create_replay_vision_read_meter_schedule,
        create_replay_vision_highlight_rebuild_schedule,
        # Gemini uploads only happen in cloud; each sweep reaps only the files tracked in this
        # deployment's own Redis index, so per-deployment scoping is inherent.
        *((create_replay_vision_gemini_cleanup_sweep_schedule,) if settings.CLOUD_DEPLOYMENT else ()),
    ),
)
