from collections import defaultdict
from typing import Any

from django.db import transaction
from django.db.models import Q

from products.experiments.backend.facade.launch_signals import connect_experiment_launched
from products.replay_vision.backend.models.replay_scanner import _START_ON_LAUNCH_KEY, ReplayScanner, ScannerType

START_ON_LAUNCH_KEY = _START_ON_LAUNCH_KEY

# A scanner waits for its launch in whichever store holds its scope. The native experiment type keeps
# both keys in `scanner_config`; a scanner moved onto `scope` keeps them there and is no longer that
# type. Matching both stores means one query serves a row either side of that move.
_WAITING_IN_CONFIG = Q(scanner_type=ScannerType.EXPERIMENT, scanner_config__start_on_launch=True)
_WAITING_IN_SCOPE = Q(scope__start_on_launch=True)


def _waiting_for(experiment_id: int) -> Q:
    """Scanners saved off to start when `experiment_id` launches, from either store."""
    return (_WAITING_IN_CONFIG & Q(scanner_config__experiment_id=experiment_id)) | (
        _WAITING_IN_SCOPE & Q(scope__experiment_id=experiment_id)
    )


def start_scanners_waiting_for_launch(
    *, team_id: int, experiment_id: int, enabled_by: str = "experiment_launch", **kwargs: Any
) -> int:
    """Turn on the experiment's scanners saved off with `start_on_launch`, and return how many.

    Runs as the launch signal's receiver, and again from the reconciler for a launch whose receiver
    failed, so it is safe to run more than once.
    """
    # Deferred: pulls in access control, and this module loads in every process at startup.
    from products.replay_vision.backend.scanner_access import creator_can_scan  # noqa: PLC0415

    started: list[ReplayScanner] = []
    with transaction.atomic():
        waiting = (
            ReplayScanner.objects.select_related("created_by", "team__organization")
            .select_for_update(of=("self",))
            .filter(_waiting_for(experiment_id), team_id=team_id, enabled=False)
        )
        for scanner in waiting:
            if not scanner.team.organization.is_ai_data_processing_approved or not creator_can_scan(scanner):
                # The sweep would turn it straight back off. It keeps waiting, so the reconciler's launch
                # catch-up starts it once consent returns, and turning it on by hand clears the marker.
                continue
            # Cleared with the enable, so a reset and relaunch never turns on a scanner its owner
            # turned off after the first launch. Cleared in whichever store carries it.
            cleared = ["enabled"]
            if isinstance(scanner.scanner_config, dict) and START_ON_LAUNCH_KEY in scanner.scanner_config:
                scanner.scanner_config = {k: v for k, v in scanner.scanner_config.items() if k != START_ON_LAUNCH_KEY}
                cleared.append("scanner_config")
            if isinstance(scanner.scope, dict) and START_ON_LAUNCH_KEY in scanner.scope:
                scanner.scope = {k: v for k, v in scanner.scope.items() if k != START_ON_LAUNCH_KEY}
                cleared.append("scope")
            # nosemgrep: semgrep.rules.security.replay-vision-alert-state-direct-mutation — enables a ReplayScanner, not an alert; scanners have no state machine.
            scanner.enabled = True
            scanner.save(update_fields=cleared)
            started.append(scanner)
    if not started:
        return 0
    # Deferred: both are heavy, and this module loads in every process at startup.
    from posthog.event_usage import report_user_action  # noqa: PLC0415

    from products.replay_vision.backend.api.scanners import scanner_lifecycle_properties  # noqa: PLC0415

    for scanner in started:
        if scanner.created_by is None:
            continue
        report_user_action(
            scanner.created_by,
            "replay_vision_scanner_enabled",
            {**scanner_lifecycle_properties(scanner), "enabled_by": enabled_by},
            team=scanner.team,
        )
    return len(started)


def start_scanners_of_launched_experiments() -> int:
    """Start the waiting scanners of every experiment that has launched, and return how many.

    The launch signal starts them, but its receiver is best-effort so it can never fail a launch.
    The launch has committed by then, so nothing else would retry a failed start.
    """
    # Deferred: the experiments replay facade pulls in the recordings query modules, which circle
    # back into this package's importers.
    from products.experiments.backend.facade.replay import launched_experiment_ids  # noqa: PLC0415

    waiting = (
        ReplayScanner.objects.filter(_WAITING_IN_CONFIG | _WAITING_IN_SCOPE, enabled=False)
        .values_list("team_id", "scanner_config__experiment_id", "scope__experiment_id")
        .distinct()
    )
    experiment_ids_by_team: dict[int, set[int]] = defaultdict(set)
    for team_id, config_experiment_id, scope_experiment_id in waiting:
        # The scope wins where both stores hold an id, the same precedence `stored_scope` reads with.
        experiment_id = scope_experiment_id if isinstance(scope_experiment_id, int) else config_experiment_id
        if isinstance(experiment_id, int):
            experiment_ids_by_team[team_id].add(experiment_id)
    started = 0
    for team_id, experiment_ids in experiment_ids_by_team.items():
        for experiment_id in launched_experiment_ids(team_id, experiment_ids):
            started += start_scanners_waiting_for_launch(
                team_id=team_id, experiment_id=experiment_id, enabled_by="experiment_launch_retry"
            )
    return started


connect_experiment_launched(
    start_scanners_waiting_for_launch, dispatch_uid="replay_vision.start_scanners_waiting_for_launch"
)
