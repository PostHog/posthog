"""Repair a team's session replay recording gate when its stored flag key no longer resolves.

A team can gate recording in two columns: `Team.session_recording_linked_flag`, which stores the
flag id alongside its key, and the V2 trigger groups in `Team.session_recording_trigger_groups`,
whose `conditions.flag` holds either a bare key or an object carrying one. The SDKs resolve both by
key, so a stored key that no longer matches its flag silently stops the team recording.
`relink_teams_on_key_change` in `session_recording_links` covers every rename that goes through
`FeatureFlag.save()`; this command repairs the references that predate that receiver, plus any left
behind by a writer that bypasses `save()`, such as the `bulk_update` in `bulk_delete`.

Only a reference whose stored id resolves to a live flag in the team's own project is rewritten. One
naming a soft-deleted flag or a flag in another project is reported and left alone, because neither
has a safe new key to adopt: a human has to decide whether the team still wants a recording gate at
all. So is a bare key that names no live flag — with no id stored beside it, nothing records which
flag it meant. A flag soft-deleted between the scan and the write is the one exception. The write
reads each key under the team's row lock, so that team follows the flag onto its current key, which
is the tombstone key when the soft delete freed the original for a new flag to claim.
"""

import json
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import fields, replace
from enum import Enum, StrEnum, auto
from typing import Any, assert_never

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import QuerySet

from posthog.dataclasses import frozen
from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import (
    STORES_A_REPLAY_GATE,
    ReplayGateRewrite,
    TriggerGroupFlagRef,
    rewritten_linked_flag,
    rewritten_trigger_groups,
    save_replay_gate_rewrites,
    stored_flag_id,
    trigger_group_flag_refs,
    trigger_groups_readable,
)


class Outcome(StrEnum):
    REPAIRED = "repaired"
    ALREADY_CORRECT = "already_correct"
    FLAG_SOFT_DELETED = "flag_soft_deleted"
    FLAG_IN_OTHER_PROJECT = "flag_in_other_project"
    FLAG_MISSING = "flag_missing"
    TEAM_MISSING = "team_missing"
    KEY_UNRESOLVABLE = "key_unresolvable"
    MALFORMED = "malformed"


class Location(StrEnum):
    LINKED_FLAG = "linked_flag"
    # One group's reference, versus a whole trigger groups column too malformed to read one out of.
    TRIGGER_GROUP = "trigger_group"
    TRIGGER_GROUPS_COLUMN = "trigger_groups_column"


@frozen
class _FlagRow:
    key: str
    deleted: bool
    project_id: int


@frozen
class _FlagIndex:
    by_id: dict[int, _FlagRow]
    live_keys: set[tuple[int, str]]

    def resolves(self, project_id: int, key: str) -> bool:
        return (project_id, key) in self.live_keys


class _Unset(Enum):
    """Distinguishes "this field does not apply here" from a stored `None`.

    A group that really has no `id` still has to report `group_id: null` rather than drop the key,
    since that is how a human locates the group. An `Enum` member rather than a bare `object()` so
    the fields it defaults can keep their real types.
    """

    TOKEN = auto()


_UNSET = _Unset.TOKEN


@frozen
class _Finding:
    """One reference the scan looked at, and what it found. Serialized straight into the report."""

    outcome: Outcome
    location: Location
    team_id: int
    project_id: int
    stored_flag: Any
    group_index: int | _Unset = _UNSET
    group_id: Any | _Unset = _UNSET
    flag_id: int | _Unset = _UNSET
    old_key: str | None | _Unset = _UNSET
    new_key: str | _Unset = _UNSET

    def written(self, outcome: Outcome, new_key: str | _Unset = _UNSET) -> "_Finding":
        """This finding as the locked write left it, carrying only a key that write really stored."""
        return replace(self, outcome=outcome, new_key=new_key)

    def as_report_row(self) -> dict[str, Any]:
        # `fields()` rather than `asdict()`, which deep-copies and would leave the sentinel
        # unrecognizable.
        row = {field.name: getattr(self, field.name) for field in fields(self)}
        return {name: value for name, value in row.items() if value is not _UNSET}

    def describe(self) -> str:
        match self.location:
            case Location.LINKED_FLAG:
                where = "linked flag"
            case Location.TRIGGER_GROUPS_COLUMN:
                where = "trigger groups column"
            case Location.TRIGGER_GROUP:
                where = f"trigger group {self.group_id!r}"
            case _:
                assert_never(self.location)
        return f"team {self.team_id} (project {self.project_id}) {where}"


def _iter_team_chunks(queryset: QuerySet[Team], chunk_size: int) -> Iterator[list[Team]]:
    # `Team` is a wide model with several large JSONFields, and the scan reads four columns.
    base = queryset.only(
        "id", "project_id", "session_recording_linked_flag", "session_recording_trigger_groups"
    ).order_by("id")
    # Keyset pagination instead of .iterator(): prod runs behind PgBouncer with server-side
    # cursors disabled, so .iterator() buffers the whole result set client-side on execute.
    last_id = 0
    while True:
        chunk = list(base.filter(id__gt=last_id)[:chunk_size])
        if not chunk:
            return
        yield chunk
        last_id = chunk[-1].id


class Command(BaseCommand):
    help = "Rewrite stale flag keys in teams' session replay recording settings"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")
        parser.add_argument("--team-id", type=int, nargs="+", help="Only scan these teams (defaults to every team)")
        parser.add_argument("--chunk-size", type=int, default=500, help="Teams to load per query (default: 500)")
        parser.add_argument("--json", action="store_true", help="Emit the report as JSON instead of prose")

    def handle(self, *args: Any, **options: Any) -> None:
        # Dry-run by default, matching the other flags repair commands: a bare invocation rewrites
        # every team's replay config and enqueues a RemoteConfig rebuild per row, so writing has
        # to be asked for.
        dry_run: bool = not options["live_run"]
        as_json: bool = options["json"]
        chunk_size: int = options["chunk_size"]
        if chunk_size < 1:
            # A zero chunk slices to an empty list, so the scan would report a clean run having
            # looked at nothing.
            raise CommandError("--chunk-size must be at least 1")

        queryset = Team.objects.filter(STORES_A_REPLAY_GATE)
        if options["team_id"]:
            queryset = queryset.filter(id__in=options["team_id"])

        outcomes: Counter[Outcome] = Counter()
        repairs: list[_Finding] = []
        unrepairable: list[_Finding] = []
        scanned_teams = 0

        for teams in _iter_team_chunks(queryset, chunk_size):
            flags = self._load_flags(teams)
            for team in teams:
                scanned_teams += 1
                for finding in self._scan_team(team, flags, dry_run=dry_run):
                    outcomes[finding.outcome] += 1
                    if finding.outcome == Outcome.REPAIRED:
                        repairs.append(finding)
                    elif finding.outcome != Outcome.ALREADY_CORRECT:
                        # already_correct rows need no follow-up and would dwarf the report, so
                        # only their count is kept.
                        unrepairable.append(finding)

        report = {
            "dry_run": dry_run,
            "scanned_teams": scanned_teams,
            "scanned_references": outcomes.total(),
            "outcomes": dict(outcomes),
            "repairs": repairs,
            "unrepairable": unrepairable,
        }
        self._report(report, as_json=as_json)

    def _load_flags(self, teams: list[Team]) -> _FlagIndex:
        flag_ids: set[int] = set()
        keys: set[str] = set()
        project_ids: set[int] = set()
        for team in teams:
            if (flag_id := stored_flag_id(team.session_recording_linked_flag)) is not None:
                flag_ids.add(flag_id)
            refs = trigger_group_flag_refs(team.session_recording_trigger_groups)
            if refs:
                # Only a team that names a flag in a trigger group widens the key probe below.
                project_ids.add(team.project_id)
            for ref in refs:
                if ref.flag_id is not None:
                    flag_ids.add(ref.flag_id)
                if ref.key is not None:
                    keys.add(ref.key)

        by_id: dict[int, _FlagRow] = {}
        if flag_ids:
            # Soft-deleted flags included, so a reference to one is reported as such rather than as
            # a dangling id.
            rows = FeatureFlag.objects_including_soft_deleted.filter(id__in=flag_ids).values_list(
                "id", "key", "deleted", "team__project_id"
            )
            by_id = {
                flag_id: _FlagRow(key=key, deleted=deleted, project_id=project_id)
                for flag_id, key, deleted, project_id in rows
            }

        live_keys: set[tuple[int, str]] = set()
        if keys and project_ids:
            # Bounded by the keys this chunk actually names. Asking for every live key in these
            # projects would pull tens of thousands of rows for a chunk spanning many of them.
            live_keys = set(
                FeatureFlag.objects.filter(team__project_id__in=project_ids, key__in=keys).values_list(
                    "team__project_id", "key"
                )
            )
        return _FlagIndex(by_id=by_id, live_keys=live_keys)

    def _scan_team(self, team: Team, flags: _FlagIndex, *, dry_run: bool) -> list[_Finding]:
        findings = [*self._scan_linked_flag(team, flags), *self._scan_trigger_groups(team, flags)]
        if dry_run:
            # The keys here are the ones the chunk read, not ones this run will write.
            return findings
        return self._write_repairs(team.pk, findings)

    def _blocked_by(self, *, flag_id: int, project_id: int, flags: _FlagIndex) -> Outcome | None:
        """What stops a stored id resolving to a flag this team can adopt a key from, or None."""
        flag = flags.by_id.get(flag_id)
        if flag is None:
            return Outcome.FLAG_MISSING
        if flag.project_id != project_id:
            return Outcome.FLAG_IN_OTHER_PROJECT
        if flag.deleted:
            return Outcome.FLAG_SOFT_DELETED
        return None

    def _scan_linked_flag(self, team: Team, flags: _FlagIndex) -> list[_Finding]:
        linked_flag = team.session_recording_linked_flag
        if linked_flag is None:
            return []

        outcome, resolved = self._classify_linked_flag(linked_flag, team.project_id, flags)
        return [
            _Finding(
                outcome=outcome,
                location=Location.LINKED_FLAG,
                team_id=team.id,
                project_id=team.project_id,
                stored_flag=linked_flag,
                **resolved,
            )
        ]

    def _classify_linked_flag(
        self, linked_flag: Any, project_id: int, flags: _FlagIndex
    ) -> tuple[Outcome, dict[str, Any]]:
        # Resolved by id: this column always stores one, and it names the flag the team meant even
        # after the key has moved on.
        stored_id = stored_flag_id(linked_flag)
        if stored_id is None:
            return Outcome.MALFORMED, {}

        resolved: dict[str, Any] = {"flag_id": stored_id}
        if (blocked := self._blocked_by(flag_id=stored_id, project_id=project_id, flags=flags)) is not None:
            return blocked, resolved

        flag = flags.by_id[stored_id]
        if linked_flag.get("key") == flag.key:
            return Outcome.ALREADY_CORRECT, resolved
        return Outcome.REPAIRED, {**resolved, "old_key": linked_flag.get("key"), "new_key": flag.key}

    def _scan_trigger_groups(self, team: Team, flags: _FlagIndex) -> list[_Finding]:
        trigger_groups = team.session_recording_trigger_groups
        if not trigger_groups:
            # RemoteConfig ignores a falsy column and falls back to the V1 fields, so an empty one
            # gates nothing and reporting it would only dilute the list a human has to work.
            return []

        if not trigger_groups_readable(trigger_groups):
            return [
                _Finding(
                    outcome=Outcome.MALFORMED,
                    location=Location.TRIGGER_GROUPS_COLUMN,
                    team_id=team.id,
                    project_id=team.project_id,
                    stored_flag=trigger_groups,
                )
            ]

        findings = []
        for ref in trigger_group_flag_refs(trigger_groups):
            outcome, resolved = self._classify_trigger_group_ref(ref, team.project_id, flags)
            findings.append(
                _Finding(
                    outcome=outcome,
                    location=Location.TRIGGER_GROUP,
                    team_id=team.id,
                    project_id=team.project_id,
                    stored_flag=ref.stored_flag,
                    group_index=ref.group_index,
                    group_id=ref.group_id,
                    **resolved,
                )
            )
        return findings

    def _classify_trigger_group_ref(
        self, ref: TriggerGroupFlagRef, project_id: int, flags: _FlagIndex
    ) -> tuple[Outcome, dict[str, Any]]:
        resolved: dict[str, Any] = {"flag_id": ref.flag_id} if ref.flag_id is not None else {}

        if ref.key is None:
            return Outcome.MALFORMED, resolved
        # Key first, unlike the linked flag column: the key is what the SDK resolves, and most
        # references are the bare string form with no id to fall back on.
        if flags.resolves(project_id, ref.key):
            return Outcome.ALREADY_CORRECT, resolved
        if ref.flag_id is None:
            return Outcome.KEY_UNRESOLVABLE, resolved
        if (blocked := self._blocked_by(flag_id=ref.flag_id, project_id=project_id, flags=flags)) is not None:
            return blocked, resolved

        # Adopting the id's key moves the gate onto whatever that flag is called now, which can be
        # a different flag than the stale key names today. The id is the stronger reference, and
        # old_key/new_key below makes the move visible in the report.
        return Outcome.REPAIRED, {**resolved, "old_key": ref.key, "new_key": flags.by_id[ref.flag_id].key}

    def _write_repairs(self, team_id: int, findings: list[_Finding]) -> list[_Finding]:
        """Rewrite the references the scan classed as repairable, and report what the write did.

        Both the stored reference and the key it should adopt are read again inside the team's row
        lock, because `_load_flags` reads each key once per chunk and a whole page of teams can be
        written after it. A rename landing in that window has already relinked this team, so
        writing the key the chunk read would put back a key no flag holds, which is the failure
        this command exists to repair. Reading inside the lock converges on the value
        `relink_teams` writes, because that relink takes this same row lock.

        A reference an admin has edited since the scan is left for the next run: the finding was
        classified from a copy that is no longer what the column holds, so rewriting it would put
        the pre-edit reference back and publish it to the SDKs.
        """
        repairs = [
            (index, finding, finding.flag_id)
            for index, finding in enumerate(findings)
            # Every repairable reference resolved an id to take its new key from, so this narrows
            # the type without dropping any of them.
            if finding.outcome == Outcome.REPAIRED and isinstance(finding.flag_id, int)
        ]
        if not repairs:
            return findings

        # `save_replay_gate_rewrites` skips `rewrite` when the team row is gone, so these stand
        # until the lock is held.
        written = {index: finding.written(Outcome.TEAM_MISSING) for index, finding, _ in repairs}

        def rewrite(locked: Team) -> ReplayGateRewrite:
            current_keys = self._current_keys(flag_id for _, _, flag_id in repairs)
            locked_refs = {
                ref.group_index: ref for ref in trigger_group_flag_refs(locked.session_recording_trigger_groups)
            }
            linked_flag: dict[str, Any] | None = None
            renames: dict[int, str] = {}

            for index, finding, flag_id in repairs:
                current_key = current_keys.get(flag_id)
                if current_key is None:
                    # A hard delete landed in this window, leaving no key to adopt. Writing the one
                    # the chunk read would store a gate the SDKs cannot resolve.
                    written[index] = finding.written(Outcome.FLAG_MISSING)
                    continue

                # Only these two locations are ever classified repairable; a whole malformed
                # trigger groups column is reported, never rewritten.
                if finding.location is Location.LINKED_FLAG:
                    rewritten = rewritten_linked_flag(
                        locked.session_recording_linked_flag, flag_id=flag_id, new_key=current_key
                    )
                    if rewritten is None:
                        written[index] = finding.written(Outcome.ALREADY_CORRECT)
                        continue
                    linked_flag = rewritten
                else:
                    ref = locked_refs.get(finding.group_index) if isinstance(finding.group_index, int) else None
                    # Matched on the group id and the stored reference as well as the index, so a
                    # group added, removed or reordered since the scan cannot shift a rewrite onto
                    # its neighbour, even one holding a byte-identical reference. Neither field
                    # stands alone: a group can store no id, and two can hold the same reference.
                    if (
                        ref is None
                        or ref.group_id != finding.group_id
                        or ref.stored_flag != finding.stored_flag
                        or ref.key == current_key
                    ):
                        written[index] = finding.written(Outcome.ALREADY_CORRECT)
                        continue
                    renames[ref.group_index] = current_key

                written[index] = finding.written(Outcome.REPAIRED, new_key=current_key)

            return ReplayGateRewrite(
                linked_flag=linked_flag,
                trigger_groups=rewritten_trigger_groups(locked.session_recording_trigger_groups, renames),
            )

        save_replay_gate_rewrites(team_id, rewrite)
        return [written.get(index, finding) for index, finding in enumerate(findings)]

    def _current_keys(self, flag_ids: Iterable[int]) -> dict[int, str]:
        """Each flag's key as it stands right now, soft-deleted flags included.

        `objects_including_soft_deleted` so a soft delete landing since the scan keeps the team on
        the tombstone key that `_free_key_held_by_soft_deleted_flags` gives the flag. That rename
        frees the original key for a new flag to claim, and a team left on it would gate recording
        on a flag it never linked.
        """
        rows = FeatureFlag.objects_including_soft_deleted.filter(pk__in=set(flag_ids)).values_list("pk", "key")
        return dict(rows)

    def _report(self, report: dict[str, Any], *, as_json: bool) -> None:
        repairs: list[_Finding] = report["repairs"]
        unrepairable: list[_Finding] = report["unrepairable"]

        if as_json:
            rows = {
                **report,
                "repairs": [finding.as_report_row() for finding in repairs],
                "unrepairable": [finding.as_report_row() for finding in unrepairable],
            }
            self.stdout.write(json.dumps(rows, indent=2, default=str))
            return

        verb = "Would repair" if report["dry_run"] else "Repaired"
        self.stdout.write(
            f"Scanned {report['scanned_teams']} team(s) gating session replay on a flag, "
            f"{report['scanned_references']} reference(s)."
        )
        self.stdout.write(f"{verb} {len(repairs)} reference(s):")
        for repair in repairs:
            self.stdout.write(f"  {repair.describe()}: flag {repair.flag_id} {repair.old_key!r} -> {repair.new_key!r}")

        for outcome, count in sorted(report["outcomes"].items()):
            if outcome != Outcome.REPAIRED:
                self.stdout.write(f"{outcome}: {count}")

        if unrepairable:
            self.stdout.write("Not repaired:")
            for row in unrepairable:
                self.stdout.write(f"  {row.describe()} [{row.outcome}]: {row.stored_flag!r}")
