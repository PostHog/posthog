from collections.abc import Iterator
from itertools import groupby
from uuid import UUID

from django.core.management.base import BaseCommand

from posthog.dataclasses import frozen

from products.skills.backend.api.skill_services import normalize_skill_file_path
from products.skills.backend.models import LLMSkillFile

READ_CHUNK_SIZE = 1000


@frozen
class SkillPathPlan:
    rewrites: list[tuple[UUID, str, str]]
    collisions: list[tuple[str, str]]
    unfixable: list[tuple[str, str]]


def plan_skill_paths(rows: list[tuple[UUID, str]]) -> SkillPathPlan:
    """Decide what to do with one skill's file rows, given `(row id, stored path)` pairs.

    A path that already normalizes to itself stays untouched. A path whose canonical form collides
    case-insensitively with another path of the same skill is reported, not rewritten: the two rows
    hold different content, so choosing a winner would silently drop one.
    """
    rewrites: list[tuple[UUID, str, str]] = []
    collisions: list[tuple[str, str]] = []
    unfixable: list[tuple[str, str]] = []
    # Seeded with every stored path, so the plan does not depend on the order the rows arrive in.
    taken = {path.lower() for _, path in rows}
    for row_id, path in rows:
        try:
            canonical = normalize_skill_file_path(path)
        except ValueError as error:
            unfixable.append((path, str(error)))
            continue
        if canonical == path:
            continue
        if canonical.lower() in taken:
            collisions.append((path, canonical))
            continue
        taken.add(canonical.lower())
        rewrites.append((row_id, path, canonical))
    return SkillPathPlan(rewrites=rewrites, collisions=collisions, unfixable=unfixable)


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
        rewritten = collided = unfixable = 0

        if not apply:
            self.stdout.write(self.style.WARNING("Dry run — pass --apply to write the rewrites."))

        for skill_id, rows in self._rows_by_skill(options["team_id"]):
            plan = plan_skill_paths(rows)
            for path, canonical in plan.collisions:
                collided += 1
                self.stdout.write(self.style.WARNING(f"skill {skill_id}: '{path}' would collide with '{canonical}'"))
            for path, reason in plan.unfixable:
                unfixable += 1
                self.stdout.write(self.style.WARNING(f"skill {skill_id}: '{path}' has no canonical form — {reason}"))
            for row_id, path, canonical in plan.rewrites:
                rewritten += 1
                self.stdout.write(f"skill {skill_id}: '{path}' -> '{canonical}'")
                if apply:
                    # A queryset update rather than `save()`, so the skill row's `updated_at` stays
                    # put: the marketplace plugin version is Max(updated_at) over a team's skills,
                    # and bumping it would re-clone every team's marketplace over a path fix.
                    LLMSkillFile.objects.filter(pk=row_id).update(path=canonical)

        verb = "Rewrote" if apply else "Would rewrite"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {rewritten} path(s); {collided} collision(s); {unfixable} unfixable path(s).")
        )

    def _rows_by_skill(self, team_id: int | None) -> Iterator[tuple[UUID, list[tuple[UUID, str]]]]:
        """Stream `(skill id, rows)`, holding one skill's paths in memory at a time.

        Ordering by skill id makes the rows arrive grouped, so collision checking sees a whole
        skill without one query per skill.
        """
        files = LLMSkillFile.objects.all()
        if team_id is not None:
            files = files.filter(skill__team_id=team_id)
        rows = files.order_by("skill_id").values_list("id", "skill_id", "path").iterator(chunk_size=READ_CHUNK_SIZE)
        for skill_id, group in groupby(rows, key=lambda row: row[1]):
            yield skill_id, [(row_id, path) for row_id, _, path in group]
