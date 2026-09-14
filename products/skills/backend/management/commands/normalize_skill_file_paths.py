from collections import defaultdict
from collections.abc import Iterator
from itertools import groupby
from uuid import UUID

from django.core.management.base import BaseCommand

from posthog.dataclasses import frozen

from products.skills.backend.api.skill_services import normalize_skill_file_path
from products.skills.backend.marketplace.adapters import bundle_paths_are_safe
from products.skills.backend.models import LLMSkillFile

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
    rows: list[tuple[UUID, str]]


def plan_skill_paths(rows: list[tuple[UUID, str]]) -> SkillPathPlan:
    """Decide what to do with one skill's file rows, given `(row id, stored path)` pairs.

    A path that already normalizes to itself stays untouched. Rows are grouped by the destination
    they want rather than walked in arrival order, so the plan is a function of the row set alone:
    `_rows_by_skill` orders by skill id only, which leaves two rows of one skill free to arrive
    either way round. Every row of a group that two rows want is reported, and none of them is
    rewritten — the rows hold different content, so choosing a winner would silently drop one.

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
            collisions.extend((path, canonical) for _, path, canonical in group if canonical != path)
            continue
        row_id, path, canonical = group[0]
        if canonical != path:
            rewrites.append((row_id, path, canonical))

    rewrites.sort(key=lambda rewrite: rewrite[1])
    collisions.sort()
    unfixable.sort()
    rewritten = {path: canonical for _, path, canonical in rewrites}
    if rewrites and not bundle_paths_are_safe([rewritten.get(path, path) for _, path in rows]):
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
                        f"skill {skill_files.skill_id}: left alone — the rewritten paths would still be unsafe to clone"
                    )
                )
            for path, canonical in plan.collisions:
                collided += 1
                self.stdout.write(
                    self.style.WARNING(f"skill {skill_files.skill_id}: '{path}' would collide with '{canonical}'")
                )
            for path, reason in plan.unfixable:
                unfixable += 1
                self.stdout.write(
                    self.style.WARNING(f"skill {skill_files.skill_id}: '{path}' has no canonical form — {reason}")
                )
            for row_id, path, canonical in plan.rewrites:
                rewritten += 1
                self.stdout.write(f"skill {skill_files.skill_id}: '{path}' -> '{canonical}'")
                if apply:
                    # A queryset update rather than `save()`, so the skill row's `updated_at` stays
                    # put: the marketplace plugin version is Max(updated_at) over a team's skills,
                    # and bumping it would re-clone every team's marketplace over a path fix.
                    LLMSkillFile.objects.filter(pk=row_id).update(path=canonical)

        verb = "Rewrote" if apply else "Would rewrite"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {rewritten} path(s); {collided} collision(s); "
                f"{unfixable} unfixable path(s); {unsafe} skill(s) left alone."
            )
        )

    def _rows_by_skill(self, team_id: int | None) -> Iterator[SkillFileRows]:
        """Stream `(skill id, rows)`, holding one skill's paths in memory at a time.

        Ordering by skill id makes the rows arrive grouped, so collision checking sees a whole
        skill without one query per skill.
        """
        files = LLMSkillFile.objects.all()
        if team_id is not None:
            files = files.filter(skill__team_id=team_id)
        rows = files.order_by("skill_id").values_list("id", "skill_id", "path").iterator(chunk_size=READ_CHUNK_SIZE)
        for skill_id, group in groupby(rows, key=lambda row: row[1]):
            yield SkillFileRows(skill_id=skill_id, rows=[(row_id, path) for row_id, _, path in group])
