from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityLog

from products.experiments.backend.facade.contracts import ExperimentHealthReaderAccess
from products.experiments.backend.health.context import PauseHistory
from products.experiments.backend.models.experiment import Experiment

# pinned: the `activity` of the entries that `ExperimentService.pause_experiment` and `resume_experiment` write.
_PAUSED = "paused"
_RESUMED = "resumed"


def load_pause_history(experiment: Experiment, *, reader_access: ExperimentHealthReaderAccess) -> PauseHistory | None:
    """
    The pause history of a paused experiment, or None. Never raises: the flag-state check then reports the disabled
    flag without saying who disabled it.
    """
    # The experiment's own `activity` action shows these entries to a caller with `activity_log:read`.
    # `can_read_flag_history` includes that scope, and also viewer access to the flag, which these entries don't
    # need. A reader without flag access gets the finding of an unknown cause, as when the read fails.
    if not experiment.is_paused or not reader_access.can_read_flag_history:
        return None
    try:
        return _load_pause_history(experiment)
    except Exception as error:
        capture_exception(error)
        return None


def _load_pause_history(experiment: Experiment) -> PauseHistory | None:
    launched_at = experiment.start_date
    if launched_at is None:
        return None
    # A pause before a reset to draft belongs to an earlier run, so only the entries since launch count.
    latest = (
        ActivityLog.objects.filter(
            team_id=experiment.team_id,
            scope="Experiment",
            item_id=str(experiment.id),
            activity__in=(_PAUSED, _RESUMED),
            created_at__gte=launched_at,
        )
        .order_by("-created_at")
        .values_list("activity", "created_at")
        .first()
    )
    return PauseHistory(
        launched_at=launched_at,
        team_timezone=experiment.team.timezone,
        paused_at=latest[1] if latest is not None and latest[0] == _PAUSED else None,
    )
