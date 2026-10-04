from typing import Any

from django.db import transaction

from posthog.event_usage import report_user_action

from products.experiments.backend.facade.launch_signals import connect_experiment_launched
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType

START_ON_LAUNCH_KEY = "start_on_launch"


def start_scanners_waiting_for_launch(*, team_id: int, experiment_id: int, **kwargs: Any) -> None:
    started: list[ReplayScanner] = []
    with transaction.atomic():
        waiting = ReplayScanner.objects.select_for_update().filter(
            team_id=team_id,
            scanner_type=ScannerType.EXPERIMENT,
            enabled=False,
            scanner_config__experiment_id=experiment_id,
            scanner_config__start_on_launch=True,
        )
        for scanner in waiting:
            # Cleared with the enable, so a reset and relaunch never turns on a scanner its owner
            # turned off after the first launch.
            scanner.scanner_config = {k: v for k, v in scanner.scanner_config.items() if k != START_ON_LAUNCH_KEY}
            scanner.enabled = True
            scanner.save(update_fields=["scanner_config", "enabled"])
            started.append(scanner)
    if not started:
        return
    # Deferred: the scanners API module is heavy, and this module loads in every process at startup.
    from products.replay_vision.backend.api.scanners import scanner_lifecycle_properties  # noqa: PLC0415

    for scanner in started:
        if scanner.created_by is None:
            continue
        report_user_action(
            scanner.created_by,
            "replay_vision_scanner_enabled",
            {**scanner_lifecycle_properties(scanner), "enabled_by": "experiment_launch"},
            team=scanner.team,
        )


connect_experiment_launched(
    start_scanners_waiting_for_launch, dispatch_uid="replay_vision.start_scanners_waiting_for_launch"
)
