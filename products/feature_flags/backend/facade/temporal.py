"""The feature flags Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.feature_flags.backend.temporal.flag_windows import ACTIVITIES, WORKFLOWS
from products.feature_flags.backend.temporal.flag_windows.schedule import create_tick_flag_windows_schedule

TEMPORAL = TemporalRegistration(
    queues=(QueueBinding(queue_setting="GENERAL_PURPOSE_TASK_QUEUE", workflows=WORKFLOWS, activities=ACTIVITIES),),
    schedules=(create_tick_flag_windows_schedule,),
)
