from collections.abc import Callable

from django.dispatch import Signal

# Sent with `team_id=` and `experiment_id=` after a launch saves, so other products react to it
# without the experiments product importing them.
experiment_launched = Signal()


def connect_experiment_launched(receiver: Callable[..., object], *, dispatch_uid: str) -> None:
    """``receiver`` gets ``team_id=`` and ``experiment_id=`` once a launch saves. A receiver that
    raises is logged and never fails the launch."""
    experiment_launched.connect(receiver, dispatch_uid=dispatch_uid)
