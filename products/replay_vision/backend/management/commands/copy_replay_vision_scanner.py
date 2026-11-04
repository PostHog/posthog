"""Copy a scanner's succeeded observations into a test project, with personal data scrubbed.

The copy is a fixed data set. Run a scanner scout against it again and again to judge a change to the
scout. Recordings are not copied, so replay links in the copy do not open.
"""

import re
import hashlib
import secrets
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from posthog.models import Team, User

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.temporal.activities.emit_observation_event import capture_observation_event
from products.replay_vision.backend.temporal.types import ScannerResult
from products.signals.backend.facade.api import forget_scratchpad_entries

EVAL_COPY_MARKER = "(eval copy"
# The variant-analysis scout reads only events older than one hour, so the newest copy lands before that.
NEWEST_COPY_AGE = timedelta(hours=2)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Ten or more digits, so dates and durations in the text stay.
_PHONE = re.compile(r"(?<!\w)\+?(?:\d[ ().-]{0,2}){9,14}\d(?!\w)")


class Scrubber:
    """Replaces emails, phone numbers and the given terms in free text, and counts each replacement."""

    # Variant keys must match the copied flag, so the scrub leaves them as they are.
    _KEPT_KEYS = frozenset({"experiment_variant", "variants", "scanner_type"})

    def __init__(self, terms: list[str]) -> None:
        self._patterns: list[tuple[str, re.Pattern[str], str]] = [
            ("email", _EMAIL, "[email]"),
            ("phone", _PHONE, "[phone]"),
            *((f"term {term!r}", re.compile(re.escape(term), re.IGNORECASE), "[redacted]") for term in terms if term),
        ]
        self.hits: Counter[str] = Counter()

    def text(self, value: str) -> str:
        for name, pattern, placeholder in self._patterns:
            value, count = pattern.subn(placeholder, value)
            self.hits[name] += count
        return value

    def json(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.json(item) for item in value]
        if isinstance(value, dict):
            return {key: item if key in self._KEPT_KEYS else self.json(item) for key, item in value.items()}
        return value


class Command(BaseCommand):
    help = (
        "Copy a Replay Vision scanner and its succeeded observations into a test project, with personal data scrubbed"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--source-scanner-id", type=UUID)
        parser.add_argument("--target-team-id", type=int)
        parser.add_argument(
            "--user-email",
            help="User who owns the copied experiment. Must be a member of the target project's organization.",
        )
        parser.add_argument(
            "--redact",
            action="append",
            default=[],
            help="A term to replace in all copied text, such as the customer's name or domain. Repeat for more terms.",
        )
        parser.add_argument("--limit", type=int, default=500, help="Copy at most this many of the newest observations")
        parser.add_argument("--commit", action="store_true", help="Write the copy. Without it, only print a preview.")
        parser.add_argument(
            "--reset-scout-tally",
            type=UUID,
            metavar="COPIED_SCANNER_ID",
            help="Delete the scout memory of a copied scanner, so the next scout run reads every observation again.",
        )

    def handle(self, *args: object, **options: Any) -> None:
        if options["reset_scout_tally"]:
            self._reset_scout_tally(options["reset_scout_tally"])
            return
        if not (options["source_scanner_id"] and options["target_team_id"] and options["user_email"]):
            raise CommandError("--source-scanner-id, --target-team-id and --user-email are required")

        source = (
            ReplayScanner.all_origins.select_related("team__organization")
            .filter(pk=options["source_scanner_id"])
            .first()
        )
        if source is None:
            raise CommandError("Source scanner not found")
        target_team = Team.objects.select_related("organization").filter(pk=options["target_team_id"]).first()
        if target_team is None:
            raise CommandError("Target team not found")
        if target_team.id == source.team_id:
            raise CommandError("Target team must not be the source scanner's team")
        user = User.objects.filter(email=options["user_email"]).first()
        if user is None:
            raise CommandError("User not found")

        observations = list(
            ReplayObservation.objects.filter(scanner=source, status=ObservationStatus.SUCCEEDED).order_by(
                "-completed_at"
            )[: options["limit"]]
        )
        if not observations:
            raise CommandError("Source scanner has no succeeded observations")
        newest = max(o.completed_at for o in observations if o.completed_at is not None)
        offset = timezone.now() - NEWEST_COPY_AGE - newest
        copy = _ScannerCopy(source, target_team, Scrubber(options["redact"]), offset)
        copies = [copy.observation(o) for o in observations]

        self.stdout.write(
            f"Source: scanner {source.id} in team {source.team_id} ({source.team.organization.name})\n"
            f"Target: team {target_team.id} ({target_team.organization.name})\n"
            f"Observations: {len(copies)}, shifted by {offset}"
        )
        self.stdout.write(f"Scrub hits in observations: {dict(copy.scrubber.hits) or 'none'}")
        if not options["commit"]:
            self.stdout.write("Preview only. Add --commit to write the copy.")
            return

        with transaction.atomic():
            experiment = copy.experiment(user)
            scanner = copy.scanner(experiment)
            for row in copies:
                row.scanner = scanner
                row.scanner_snapshot = copy.snapshot(row.scanner_snapshot, scanner, experiment)
            ReplayObservation.objects.bulk_create(copies)
            # bulk_create stamps `created_at` with the time now, so set the shifted times again.
            for row, source_row in zip(copies, observations):
                row.created_at = source_row.created_at + offset
            ReplayObservation.objects.bulk_update(copies, ["created_at"])

        failed = 0
        for row in copies:
            try:
                model_output = ScannerResult.model_validate(row.scanner_result).model_output
                capture_observation_event(row, target_team, model_output, timestamp=row.completed_at or newest)
            except Exception as e:
                failed += 1
                self.stderr.write(f"Event for observation {row.id} failed: {e}")

        self.stdout.write(f"Scrub hits in total: {dict(copy.scrubber.hits) or 'none'}")
        self.stdout.write(
            f"Copied scanner {scanner.id} ({scanner.name}) with {len(copies)} observations, "
            f"{len(copies) - failed} events"
            + (f", experiment {experiment.id}" if experiment else "")
            + f"\n/project/{target_team.id}/replay-vision/{scanner.id}"
        )

    def _reset_scout_tally(self, scanner_id: UUID) -> None:
        scanner = ReplayScanner.objects.filter(pk=scanner_id).first()
        # Only a copy, so the reset can never wipe a real scanner's scout memory.
        if scanner is None or scanner.enabled or EVAL_COPY_MARKER not in scanner.name:
            raise CommandError("Scanner not found, or it is not a disabled eval copy")
        deleted = forget_scratchpad_entries(team_id=scanner.team_id, key_prefix=f"{scanner.id}:")
        self.stdout.write(f"Deleted {deleted} scratchpad entries for scanner {scanner.id}")


class _ScannerCopy:
    def __init__(self, source: ReplayScanner, target_team: Team, scrubber: Scrubber, offset: timedelta) -> None:
        self.source = source
        self.target_team = target_team
        self.scrubber = scrubber
        self.offset = offset
        # A fresh salt per copy, so a pseudonym can't be traced back by hashing known ids.
        self._salt = secrets.token_hex(16)
        self.tag = self._salt[:8]

    def _pseudonym(self, value: str) -> str:
        return hashlib.sha256(f"{self._salt}:{value}".encode()).hexdigest()[:32]

    def _shift(self, value: datetime | None) -> datetime | None:
        return value + self.offset if value is not None else None

    def observation(self, source_row: ReplayObservation) -> ReplayObservation:
        return ReplayObservation(
            team=self.target_team,
            session_id=f"eval-{self._pseudonym(source_row.session_id)}",
            distinct_id=f"eval-person-{self._pseudonym(source_row.distinct_id)}" if source_row.distinct_id else None,
            session_started_at=self._shift(source_row.session_started_at),
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot=source_row.scanner_snapshot,
            scanner_result=self.scrubber.json(source_row.scanner_result),
            triggered_by=ObservationTrigger.SCHEDULE,
            started_at=self._shift(source_row.started_at),
            completed_at=self._shift(source_row.completed_at),
        )

    def experiment(self, user: User) -> Experiment | None:
        scope = self.source.experiment_scope()
        if not scope:
            return None
        source_experiment = Experiment.objects.get(pk=scope["experiment_id"], team_id=self.source.team_id)
        experiment = ExperimentService(team=self.source.team, user=user).copy_experiment_to_project(
            source_experiment,
            self.target_team,
            feature_flag_key=f"eval-copy-{self.tag}",
            name=f"{self.scrubber.text(source_experiment.name)} {EVAL_COPY_MARKER} {self.tag})",
        )
        # update(), not save(), so a start date does not fire the launch receivers.
        Experiment.objects.filter(pk=experiment.pk).update(
            description=self.scrubber.text(source_experiment.description or ""),
            start_date=self._shift(source_experiment.start_date),
            end_date=self._shift(source_experiment.end_date),
        )
        experiment.refresh_from_db()
        return experiment

    def _remap_config(self, config: dict[str, Any] | None, experiment: Experiment | None) -> dict[str, Any]:
        remapped = self.scrubber.json(dict(config or {}))
        remapped.pop("start_on_launch", None)
        if experiment is not None and "experiment_id" in remapped:
            remapped["experiment_id"] = experiment.id
        return remapped

    def scanner(self, experiment: Experiment | None) -> ReplayScanner:
        is_experiment_type = self.source.scanner_type == ScannerType.EXPERIMENT
        return ReplayScanner.objects.create(
            team=self.target_team,
            name=f"{self.scrubber.text(self.source.name)} {EVAL_COPY_MARKER} {self.tag})",
            description=self.scrubber.text(self.source.description),
            goal=self.scrubber.text(self.source.goal) if self.source.goal else self.source.goal,
            scanner_type=self.source.scanner_type,
            scanner_config=self._remap_config(self.source.scanner_config, experiment),
            experiment_targeting=(
                None
                if is_experiment_type or experiment is None
                else self._remap_config(self.source.experiment_targeting, experiment)
            ),
            sampling_rate=self.source.sampling_rate,
            sampling_mode=self.source.sampling_mode,
            provider=self.source.provider,
            model=self.source.model,
            scanner_version=self.source.scanner_version,
            enabled=False,
            emits_signals=False,
        )

    def snapshot(
        self, source_snapshot: dict[str, Any], scanner: ReplayScanner, experiment: Experiment | None
    ) -> dict[str, Any]:
        snapshot = dict(source_snapshot)
        # Learned rulesets and the recording filter belong to the source team.
        snapshot.pop("learned_ruleset_ids", None)
        snapshot["query"] = None
        snapshot["name"] = scanner.name
        snapshot["emits_signals"] = False
        snapshot["scanner_config"] = self._remap_config(snapshot.get("scanner_config"), experiment)
        if snapshot.get("experiment_targeting"):
            snapshot["experiment_targeting"] = (
                self._remap_config(snapshot["experiment_targeting"], experiment) if experiment else None
            )
        return snapshot
