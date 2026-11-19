"""The growth Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from django.conf import settings

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.growth.backend.temporal import (
    ACTIVITIES as GROWTH_ACTIVITIES,
    WORKFLOWS as GROWTH_WORKFLOWS,
)
from products.growth.backend.temporal.signup_enrichment.schedule import (
    create_harmonic_status_poll_schedule,
    create_icp_reenrichment_sweep_schedule,
)

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE",
            workflows=tuple(GROWTH_WORKFLOWS),
            activities=tuple(GROWTH_ACTIVITIES),
        ),
        # Dedicated landing zone for signup enrichment. Defaults to the general-purpose queue name (so it
        # merges into that fleet until a dedicated worker exists); setting SIGNUP_ENRICHMENT_TASK_QUEUE on a
        # worker registers these workflows under the dedicated queue, letting dispatch move there with no code change.
        QueueBinding(
            queue_setting="SIGNUP_ENRICHMENT_TASK_QUEUE",
            workflows=tuple(GROWTH_WORKFLOWS),
            activities=tuple(GROWTH_ACTIVITIES),
        ),
    ),
    # The sweep re-fetches each region's own orgs from Harmonic, and only US and EU carry the key.
    schedules=(
        (create_icp_reenrichment_sweep_schedule, create_harmonic_status_poll_schedule)
        if settings.CLOUD_DEPLOYMENT in ("US", "EU")
        else ()
    ),
)
