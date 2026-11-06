from datetime import datetime

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityLog

from products.experiments.backend.health.delays import ZERO_EXPOSURES_GRACE_HOURS
from products.experiments.backend.models.experiment import Experiment


def hours_since_launch(experiment: Experiment, at: datetime, *, can_read_flag_history: bool) -> float | None:
    """
    The hours from the experiment's launch to `at`, which the exposure checks wait on. The start date can be moved
    back to before the launch, when the flag didn't serve variants yet, so the wait counts from the later of the start
    date and the latest launch in the activity log. The activity log needs the access of the flag history, so a reader
    without it waits from the start date.
    """
    start_date = experiment.start_date
    if start_date is None:
        return None
    hours = (at - start_date).total_seconds() / 3600
    # A wait that holds by the start date also holds by the launch, which can only be later.
    if hours < ZERO_EXPOSURES_GRACE_HOURS or not can_read_flag_history:
        return hours
    launched_at = _latest_launch(experiment)
    if launched_at is None or launched_at <= start_date:
        return hours
    return (at - launched_at).total_seconds() / 3600


def _latest_launch(experiment: Experiment) -> datetime | None:
    # A launch logs the start date that it sets on a draft. An experiment created with a start date logs none, and its
    # start date stands.
    try:
        return (
            ActivityLog.objects.filter(
                team_id=experiment.team_id,
                scope="Experiment",
                item_id=str(experiment.id),
                activity="updated",
                detail__contains={"changes": [{"field": "start_date", "before": None}]},
            )
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
    except Exception as error:
        # The start date is a safe fallback, so a failed lookup must not fail the exposure answer.
        capture_exception(error)
        return None
