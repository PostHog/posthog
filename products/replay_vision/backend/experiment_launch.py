from collections import defaultdict
from typing import Any

from django.db import transaction

from products.experiments.backend.facade.launch_signals import connect_experiment_launched
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType

START_ON_LAUNCH_KEY = "start_on_launch"


def start_scanners_waiting_for_launch(
    *, team_id: int, experiment_id: int, enabled_by: str = "experiment_launch", **kwargs: Any
) -> int:
    """Turn on the experiment's scanners saved off with `start_on_launch`, and return how many.

    Runs as the launch signal's receiver, and again from the reconciler for a launch whose receiver
    failed, so it is safe to run more than once.
    """
    started: list[ReplayScanner] = []
    with transaction.atomic():
        waiting = (
            ReplayScanner.objects.select_related("created_by", "team")
            .select_for_update(of=("self",))
            .filter(
                team_id=team_id,
                scanner_type=ScannerType.EXPERIMENT,
                enabled=False,
                scanner_config__experiment_id=experiment_id,
                scanner_config__start_on_launch=True,
            )
        )
        for scanner in waiting:
            # Cleared with the enable, so a reset and relaunch never turns on a scanner its owner
            # turned off after the first launch.
            scanner.scanner_config = {k: v for k, v in scanner.scanner_config.items() if k != START_ON_LAUNCH_KEY}
            # nosemgrep: semgrep.rules.security.replay-vision-alert-state-direct-mutation — enables a ReplayScanner, not an alert; scanners have no state machine.
            scanner.enabled = True
            scanner.save(update_fields=["scanner_config", "enabled"])
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
        ReplayScanner.objects.filter(
            scanner_type=ScannerType.EXPERIMENT, enabled=False, scanner_config__start_on_launch=True
        )
        .values_list("team_id", "scanner_config__experiment_id")
        .distinct()
    )
    experiment_ids_by_team: dict[int, set[int]] = defaultdict(set)
    for team_id, experiment_id in waiting:
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
