from django.db import connection

from posthog.dataclasses import frozen


@frozen
class FlatRuleTeam:
    team_id: int
    flat_rules: int


# Rewrites pre-combiner flat bot rules ({key, matcher, pattern} on the rule itself) into the
# multi-condition shape ({combiner, items}) the current code reads. Everything happens inside one
# UPDATE per team: only the customBotDefinitions key of team.modifiers changes, so concurrent
# writes to other modifier keys cannot be clobbered and their query cache keys do not churn.
# Entries already in the new shape and non-object entries pass through untouched, which makes the
# statement idempotent. The condition id gets a "-condition" suffix because the settings editor
# keys rules and conditions in one id-keyed drag-and-drop context.
# The CASE guard is load-bearing: AND does not guarantee evaluation order in PostgreSQL, so
# without it jsonb_array_elements can run against a non-array value (a hand-edited or corrupt
# modifiers entry) and abort the whole statement for every team.
_FLAT_ENTRY_PREDICATE = """
CASE WHEN jsonb_typeof(modifiers->'customBotDefinitions') = 'array' THEN
    EXISTS (
        SELECT 1
        FROM jsonb_array_elements(modifiers->'customBotDefinitions') AS entry
        WHERE jsonb_typeof(entry) = 'object' AND NOT (entry ? 'items') AND entry ? 'key'
    )
ELSE false END
"""

_FIND_TEAMS_SQL = f"""
SELECT id,
       (
           SELECT count(*)
           FROM jsonb_array_elements(modifiers->'customBotDefinitions') AS entry
           WHERE jsonb_typeof(entry) = 'object' AND NOT (entry ? 'items') AND entry ? 'key'
       ) AS flat_rules
FROM posthog_team
WHERE {_FLAT_ENTRY_PREDICATE}
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
  AND {_FLAT_ENTRY_PREDICATE}
"""


def find_teams_with_flat_rules() -> list[FlatRuleTeam]:
    with connection.cursor() as cursor:
        cursor.execute(_FIND_TEAMS_SQL)
        return [FlatRuleTeam(team_id=row[0], flat_rules=row[1]) for row in cursor.fetchall()]


def migrate_team(team_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(_MIGRATE_TEAM_SQL, [team_id])
        return cursor.rowcount == 1
