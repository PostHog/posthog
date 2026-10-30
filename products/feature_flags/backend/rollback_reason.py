"""The reason a person gives for an edit that lowers the exposure of a flag.

Flag rollback suggestions learn from these answers which rollbacks followed errors. The answer is stored on the
activity log entry of the edit.
"""

from django.db import models

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityContextBase

from products.feature_flags.backend.exposure_change import ExposureDirection


class RollbackReason(models.TextChoices):
    ERRORS = "errors", "Errors or bugs"
    METRICS = "metrics", "Metrics got worse"
    PLANNED = "planned", "It was planned"
    WRONG_CONFIGURATION = "wrong_configuration", "Wrong configuration"
    OTHER = "other", "Other"


@frozen(slots=False)  # The activity log encoder writes a context out through __dict__.
class RollbackReasonContext(ActivityContextBase):
    rollback_reason: RollbackReason
    rollback_reason_note: str | None
    # A client can send a reason with any edit, so the direction that the server classified tells a reason for a
    # rollback from a reason for another edit.
    exposure_direction: ExposureDirection
