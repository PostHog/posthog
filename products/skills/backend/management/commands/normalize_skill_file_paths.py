from collections import defaultdict
from collections.abc import Iterator
from itertools import groupby
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.skills.backend.api.skill_services import compute_file_path_problems, normalize_skill_file_path
from products.skills.backend.models import LLMSkill, LLMSkillFile

READ_CHUNK_SIZE = 1000


@frozen
class SkillPathPlan:
    rewrites: list[tuple[UUID, str, str]]
    collisions: list[tuple[str, str]]
    unfixable: list[tuple[str, str]]
    unsafe: bool


@frozen
class SkillFileRows:
    skill_id: UUID
    team_id: int
    name: str
    version: int
    rows: list[tuple[UUID, str]]

    @property
    def label(self) -> str:
        return f"skill id={self.skill_id} team_id={self.team_id} name='{self.name}' version={self.version}"


def plan_skill_paths(rows: list[tuple[UUID, str]]) -> SkillPathPlan:
    """Decide what to do with one skill's file rows, given `(row id, stored path)` pairs.

    A path that already normalizes to itself stays untouched. Rows are grouped by the destination
    they want rather than walked in arrival order, so the plan is a function of the row set alone:
    `_rows_by_skill` orders by skill id only, which leaves two rows of one skill free to arrive
    either way round. Every row of a group that two rows want is reported, and none of them is
    rewritten — the rows hold different content, so choosing a winner would silently drop one. A
    report names the stored paths of the group, because the shared destination is a path the
    operator cannot look up.

    The rewrites are then kept only if the whole resulting path set passes the same gate the bundle
    uses. A rewrite turns one flat name into a directory, so `assets\\logo.png` beside a file named
    `assets` clones today and fails to clone once it becomes `assets/logo.png`. The gate counts the
    generated SKILL.md and Codex sidecar and rejects those ancestor conflicts, so a skill it turns
    down keeps every stored path and is reported for manual repair.
    """
    unfixable: list[tuple[str, str]] = []
    claimants: dict[str, list[tuple[UUID, str, str]]] = defaultdict(list)
    for row_id, path in rows:
        try:
            canonical = normalize_skill_file_path(path)
        except ValueError as error:
            unfixable.append((path, str(error)))
            continue
        claimants[canonical.lower()].append((row_id, path, canonical))

    rewrites: list[tuple[UUID, str, str]] = []
    collisions: list[tuple[str, str]] = []
    for group in claimants.values():
        if len(group) > 1:
            stored = sorted(path for _, path, _ in group)
            for _, path, canonical in group:
                if canonical != path:
                    collisions.extend((path, conflict) for conflict in stored if conflict != path)
            continue
        row_id, path, canonical = group[0]
        if canonical != path:
            rewrites.append((row_id, path, canonical))

    rewrites.sort(key=lambda rewrite: rewrite[1])
    collisions.sort()
    unfixable.sort()
    rewritten = {path: canonical for _, path, canonical in rewrites}
    if rewrites and compute_file_path_problems([rewritten.get(path, path) for _, path in rows]):
        return SkillPathPlan(rewrites=[], collisions=collisions, unfixable=unfixable, unsafe=True)
    return SkillPathPlan(rewrites=rewrites, collisions=collisions, unfixable=unfixable, unsafe=False)


class Command(BaseCommand):
    help = (
        "Rewrite bundled skill file paths stored before the write-time path validator landed. "
        "A skill that holds one is skipped from the marketplace bundle entirely."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only process files of this team's skills")
        parser.add_argument("--apply", action="store_true", help="Write the rewrites. Without it, this is a dry run.")

    def handle(self, *args, **options) -> None:
        apply: bool = options["apply"]
        rewritten = collided = unfixable = unsafe = 0

        if not apply:
            self.stdout.write(self.style.WARNING("Dry run — pass --apply to write the rewrites."))

        for skill_files in self._rows_by_skill(options["team_id"]):
            plan = plan_skill_paths(skill_files.rows)
            if plan.unsafe:
                unsafe += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"{skill_files.label}: left alone — the rewritten paths would still be unsafe to clone"
                    )
                )
            for path, conflict in plan.collisions:
                collided += 1
                self.stdout.write(
                    self.style.WARNING(f"{skill_files.label}: '{path}' would collide with stored '{conflict}'")
                )
            for path, reason in plan.unfixable:
                unfixable += 1
                self.stdout.write(self.style.WARNING(f"{skill_files.label}: '{path}' has no canonical form — {reason}"))
            for _, path, canonical in plan.rewrites:
                rewritten += 1
                self.stdout.write(f"{skill_files.label}: '{path}' -> '{canonical}'")
            if apply and plan.rewrites:
                self._apply(skill_files.skill_id, plan.rewrites)

        verb = "Rewrote" if apply else "Would rewrite"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {rewritten} path(s); {collided} collision(s); "
                f"{unfixable} unfixable path(s); {unsafe} skill(s) left alone."
            )
        )

    def _apply(self, skill_id: UUID, rewrites: list[tuple[UUID, str, str]]) -> None:
        """Write one skill's rewrites and advance the version that makes clients pull them.

        `LLMSkillFile` carries no timestamp, so writing a file row moves nothing on its own. The
        marketplace plugin version is Max(updated_at) over a team's skill rows, the synthesized repo
        is cached under it, and `marketplace.json` publishes it as the label that triggers a re-pull
        — the same bump `archive_skill` and `rename_skill` make for the same reason. The two writes
        share a transaction because a rewrite that lands without its bump is invisible for good: a
        re-run finds the paths canonical, plans nothing, and never bumps.
        """
        with transaction.atomic():
            for row_id, _, canonical in rewrites:
                LLMSkillFile.objects.filter(pk=row_id).update(path=canonical)
            # A queryset update bypasses auto_now, so the timestamp is set explicitly.
            LLMSkill.objects.filter(pk=skill_id).update(updated_at=timezone.now())

    def _rows_by_skill(self, team_id: int | None) -> Iterator[SkillFileRows]:
        """Yield each skill's `(row id, path)` pairs as one group.

        Ordering by skill id makes the rows arrive grouped, so collision checking sees a whole
        skill without one query per skill. The skill's team, name and version join onto the same
        query, so a reported row names a skill an operator can find without a second lookup.

        `chunk_size` bounds the fetch only where server-side cursors are on. Cloud sets
        `DISABLE_SERVER_SIDE_CURSORS` behind PgBouncer, so `.iterator()` buffers the whole result
        set and an unfiltered run holds one tuple per file row. `LLMSkillFile` is per-team authored
        config with a per-skill file cap, not an event table, so that is acceptable for a one-off
        operator command. Pass `--team-id` to bound a run.
        """
        files = LLMSkillFile.objects.all()
        if team_id is not None:
            files = files.filter(skill__team_id=team_id)
        rows = (
            files.order_by("skill_id")
            .values_list("id", "skill_id", "skill__team_id", "skill__name", "skill__version", "path")
            .iterator(chunk_size=READ_CHUNK_SIZE)
        )
        for skill_id, group in groupby(rows, key=lambda row: row[1]):
            grouped = list(group)
            _, _, skill_team_id, name, version, _ = grouped[0]
            yield SkillFileRows(
                skill_id=skill_id,
                team_id=skill_team_id,
                name=name,
                version=version,
                rows=[(row_id, path) for row_id, _, _, _, _, path in grouped],
            )
