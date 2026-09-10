from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection

# Rewrites pre-combiner flat bot rules ({key, matcher, pattern} on the rule itself) into the
# multi-condition shape ({combiner, items}) the current code reads. Everything happens inside one
# UPDATE per team: only the customBotDefinitions key of team.modifiers changes, so concurrent
# writes to other modifier keys cannot be clobbered and their query cache keys do not churn.
# Entries already in the new shape and non-object entries pass through untouched, which makes the
# statement idempotent. The condition id gets a "-condition" suffix because the settings editor
# keys rules and conditions in one id-keyed drag-and-drop context.
_FLAT_ENTRY_PREDICATE = """
EXISTS (
    SELECT 1
    FROM jsonb_array_elements(modifiers->'customBotDefinitions') AS entry
    WHERE jsonb_typeof(entry) = 'object' AND NOT (entry ? 'items') AND entry ? 'key'
)
"""

_FIND_TEAMS_SQL = f"""
SELECT id,
       (
           SELECT count(*)
           FROM jsonb_array_elements(modifiers->'customBotDefinitions') AS entry
           WHERE jsonb_typeof(entry) = 'object' AND NOT (entry ? 'items') AND entry ? 'key'
       ) AS flat_rules
FROM posthog_team
WHERE modifiers ? 'customBotDefinitions'
  AND {_FLAT_ENTRY_PREDICATE}
ORDER BY id
"""

_MIGRATE_TEAM_SQL = f"""
UPDATE posthog_team
SET modifiers = jsonb_set(
    modifiers,
    '{{customBotDefinitions}}',
    (
        SELECT jsonb_agg(
            CASE
                WHEN jsonb_typeof(entry) != 'object' OR entry ? 'items' OR NOT (entry ? 'key') THEN entry
                ELSE jsonb_build_object(
                    'id', entry->'id',
                    'name', entry->'name',
                    'combiner', 'AND',
                    'items', jsonb_build_array(
                        jsonb_build_object(
                            'id', (entry->>'id') || '-condition',
                            'key', entry->'key',
                            'matcher', entry->'matcher',
                            'pattern', entry->'pattern'
                        )
                    )
                ) || CASE
                    WHEN entry ? 'category' THEN jsonb_build_object('category', entry->'category')
                    ELSE '{{}}'::jsonb
                END
            END
        )
        FROM jsonb_array_elements(modifiers->'customBotDefinitions') AS entry
    )
)
WHERE id = %s
  AND modifiers ? 'customBotDefinitions'
  AND {_FLAT_ENTRY_PREDICATE}
"""


def find_teams_with_flat_rules() -> list[tuple[int, int]]:
    with connection.cursor() as cursor:
        cursor.execute(_FIND_TEAMS_SQL)
        return [(row[0], row[1]) for row in cursor.fetchall()]


def migrate_team(team_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(_MIGRATE_TEAM_SQL, [team_id])
        return cursor.rowcount == 1


class Command(BaseCommand):
    help = (
        "Rewrite pre-combiner flat custom bot rules stored on team.modifiers into the "
        "multi-condition shape. Dry run by default; pass --execute to apply."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--execute", action="store_true", help="Apply the rewrite. Without it, only report.")

    def handle(self, *args: Any, **options: Any) -> None:
        teams = find_teams_with_flat_rules()
        if not teams:
            self.stdout.write("No teams with flat custom bot rules found.")
            return

        total_rules = sum(count for _, count in teams)
        self.stdout.write(f"{len(teams)} team(s) with {total_rules} flat rule(s):")
        for team_id, count in teams:
            self.stdout.write(f"  team {team_id}: {count} flat rule(s)")

        if not options["execute"]:
            self.stdout.write("Dry run - nothing changed. Re-run with --execute to apply.")
            return

        migrated = sum(1 for team_id, _ in teams if migrate_team(team_id))
        self.stdout.write(f"Migrated {migrated}/{len(teams)} team(s).")
