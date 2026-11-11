"""The access rules a migration source needs, so that moving a self-managed table into it changes nobody's access.

A self-managed table has no source, so access to it resolves from the table's own rules and the rules for the
whole warehouse (`warehouse_objects`). Once a source adopts the table, access also falls back to the rules on
that source and then to the rules for all sources (`RESOURCE_FALLBACK_MAP` in the access control facade). The
source also has access of its own: to its settings, its schemas and its syncs, and through them to the files
the table reads.

So each migration source gets rules that make two things true for every member, whatever roles the member
has, under both resolution orders an organization can use:

- the member's access to each table of the source is the same before and after the source adopts it, and
- the member's access to the source is never more than their access to each of its tables.

The rules copy the table's member and role rules, which decide on the table before anything reaches the
source, and add a default rule on the source when one is needed. When no such rules exist, the table can't
move. Tables of one bucket share a source only when they need the same rules (see `SourceAccessPlan.signature`).

The prediction mirrors `UserAccessControl` (`_object_access_level_from_rows` and
`_most_specific_object_access_from_rows`). The tests check it against that code.
"""

import json
import hashlib
import itertools
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen

from products.access_control.backend.facade.api import access_rules, replace_object_access_rules
from products.access_control.backend.facade.contracts import AccessRule, ObjectAccessRuleInput
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

# The `connection_metadata` key of a source the migration created.
MIGRATION_MARKER_KEY = "self_managed_migration"

TABLE_RESOURCE = "warehouse_table"
WAREHOUSE_RESOURCE = "warehouse_objects"
SOURCE_RESOURCE = "external_data_source"

LEVELS: tuple[str, ...] = ("none", "viewer", "editor", "manager")
# The level a table or a source resolves to when no rule decides (`default_access_level`).
_SYSTEM_DEFAULT = "editor"
# Each role profile doubles the subjects to check, so a rule set that names more is refused.
_MAX_ROLE_PROFILES = 10

# The start of the error a sync raises when it must not replace a self-managed table. The import
# classifies it as permanent, so the job fails once and syncing stops until someone fixes the rules.
ADOPTION_ACCESS_ERROR = "PostHog did not replace the self-managed table"

TABLE_RULES_REASON = "the table has its own access rules, which the source PostHog would create can't carry"
PROJECT_RULES_REASON = "the project has access rules for sources or for the warehouse, which the move would change"
ROLES_REASON = "the access rules name too many roles to check"

_Subject = Literal["member", "role", "default"]
# Most specific first, the order most-specific resolution reads one scope's rules in.
_SUBJECTS: tuple[_Subject, ...] = ("member", "role", "default")
_Scope = Literal["table", "warehouse", "sources", "source"]
_SCOPES: tuple[_Scope, ...] = ("table", "warehouse", "sources", "source")


@frozen
class SourceRule:
    """One rule on a migration source. With no member and no role, it is the source's default rule."""

    access_level: str
    organization_member_id: str | None = None
    role_id: str | None = None

    @property
    def subject(self) -> _Subject:
        if self.organization_member_id is not None:
            return "member"
        if self.role_id is not None:
            return "role"
        return "default"


@frozen
class SourceAccessPlan:
    """The rules a migration source needs for its tables to keep their access."""

    rules: tuple[SourceRule, ...] = ()

    @property
    def signature(self) -> str:
        """Identifies the rules, so only tables that need the same rules share a source. Empty without rules."""
        if not self.rules:
            return ""
        payload = json.dumps([[r.access_level, r.organization_member_id, r.role_id] for r in self.rules])
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def describe(self) -> str:
        parts = []
        for rule in self.rules:
            subject = {
                "member": f"member {rule.organization_member_id}",
                "role": f"role {rule.role_id}",
                "default": "everyone",
            }[rule.subject]
            parts.append(f"{subject}={rule.access_level}")
        return ", ".join(parts)


@frozen
class _Row:
    level: str
    subject: _Subject


class AdoptionAccessError(Exception):
    """The access rules changed after the migration, so the first sync must not replace the table."""


def _rank(level: str) -> int:
    return LEVELS.index(level)


def _highest(rows: Iterable[_Row]) -> str:
    return max((row.level for row in rows), key=_rank)


def _decision(rows: Sequence[_Row]) -> _Row | None:
    """The deciding row of one scope under most-specific resolution: the member's, then the roles', then the default."""
    for subject in _SUBJECTS:
        group = [row for row in rows if row.subject == subject]
        if group:
            return _Row(level=_highest(group), subject=subject)
    return None


def _legacy_level(
    object_rows: Sequence[_Row],
    parent_rows: Sequence[_Row] | None,
    resource_rows: Sequence[_Row],
    parent_resource_rows: Sequence[_Row],
) -> str:
    """`UserAccessControl._object_access_level_from_rows`, for a member who is no admin and not the creator.

    `parent_rows` is None for an object without a fallback parent: a self-managed table, or a source.
    """
    explicit = [row for row in object_rows if row.subject != "default"]
    if explicit:
        return _highest(explicit)
    if object_rows and _highest(object_rows) == "none":
        return "none"
    if parent_rows:
        return _highest(parent_rows)
    if resource_rows:
        return _highest(resource_rows)
    if parent_rows is not None and parent_resource_rows:
        return _highest(parent_resource_rows)
    if object_rows:
        return _highest(object_rows)
    return _SYSTEM_DEFAULT


def _most_specific_level(
    object_rows: Sequence[_Row],
    parent_rows: Sequence[_Row] | None,
    resource_rows: Sequence[_Row],
    parent_resource_rows: Sequence[_Row],
) -> str:
    """`UserAccessControl._most_specific_object_access_from_rows`, for a member who is no admin and not the creator."""

    def resource_level() -> str:
        if resource_rows:
            return _decided_level(resource_rows)
        if parent_rows is not None and parent_resource_rows:
            return _decided_level(parent_resource_rows)
        return _SYSTEM_DEFAULT

    for rows in (object_rows, parent_rows or ()):
        row = _decision(rows)
        if row is not None:
            # A default grant on the object or its parent can't widen "none" for the resource.
            if row.subject == "default" and row.level != "none" and resource_level() == "none":
                return "none"
            return row.level
    return resource_level()


def _decided_level(rows: Sequence[_Row]) -> str:
    row = _decision(rows)
    assert row is not None
    return row.level


class TeamAccessRules:
    """The rules of one team that decide access to its warehouse tables and its sources.

    Rules that resolution never applies (a member or a role of another organization) are left out.
    Several rows for one subject on one object act as their highest level, so they count as one.
    """

    def __init__(self, team_id: int) -> None:
        self.team_id = team_id
        rows = [
            rule
            for rule in access_rules(team_id=team_id, resources=(TABLE_RESOURCE, WAREHOUSE_RESOURCE, SOURCE_RESOURCE))
            if rule.applies
        ]
        self._warehouse = _subject_rules(r for r in rows if r.resource == WAREHOUSE_RESOURCE and r.resource_id is None)
        self._sources = _subject_rules(r for r in rows if r.resource == SOURCE_RESOURCE and r.resource_id is None)
        by_object: dict[tuple[str, str], list[AccessRule]] = defaultdict(list)
        for rule in rows:
            if rule.resource_id is not None and rule.resource in (TABLE_RESOURCE, SOURCE_RESOURCE):
                by_object[(rule.resource, rule.resource_id)].append(rule)
        self._objects = {key: _subject_rules(rules) for key, rules in by_object.items()}
        self._plans: dict[tuple[SourceRule, ...], SourceAccessPlan | str] = {}

    def source_rules(self, source_id: str) -> tuple[SourceRule, ...]:
        """The rules on a source as they are now, in the order a plan lists them."""
        return self._objects.get((SOURCE_RESOURCE, source_id), ())

    def plan_for(self, table_id: str) -> SourceAccessPlan | str:
        """The rules a source needs for the table to keep its access, or the reason no rules can."""
        table_rules = self._objects.get((TABLE_RESOURCE, table_id), ())
        if table_rules not in self._plans:
            self._plans[table_rules] = self._plan(table_rules)
        return self._plans[table_rules]

    def _plan(self, table_rules: tuple[SourceRule, ...]) -> SourceAccessPlan | str:
        unknown = next(
            (
                rule.access_level
                for rule in (*table_rules, *self._warehouse, *self._sources)
                if rule.access_level not in LEVELS
            ),
            None,
        )
        if unknown is not None:
            return f"an access rule has the level '{unknown}', which PostHog doesn't know"
        found = self._search(table_rules)
        if found is not None:
            return found
        # When the same table without rules of its own could move, its own rules are the cause.
        if table_rules and isinstance(self._search(()), SourceAccessPlan):
            return TABLE_RULES_REASON
        return PROJECT_RULES_REASON

    def _search(self, table_rules: tuple[SourceRule, ...]) -> SourceAccessPlan | str | None:
        """The first source rules that keep every member's access, or None when no rules can."""
        # A member or role rule on the table decides before anything reaches the source. So a copy of
        # it on the source changes nothing on the table, and gives that subject equal access to both.
        copies = tuple(rule for rule in table_rules if rule.subject != "default")
        table_default = next((rule.access_level for rule in table_rules if rule.subject == "default"), None)
        # The table's own default comes first, then no default, so the source follows the table where it can.
        for source_default in dict.fromkeys([table_default, None, *LEVELS]):
            rules = _sorted([*copies, *([SourceRule(access_level=source_default)] if source_default else [])])
            verdict = self._keeps_access(table_rules, rules)
            if verdict is True:
                return SourceAccessPlan(rules=rules)
            if isinstance(verdict, str):
                return verdict
        return None

    def _keeps_access(self, table_rules: tuple[SourceRule, ...], source_rules: tuple[SourceRule, ...]) -> bool | str:
        """Whether every member keeps their access to the table, and gets no more to the source than to the table.

        Checked for each kind of member (the rules that name them) with each combination of roles,
        because a member's roles can change at any time, and under both resolution orders, because an
        organization can change its order. Admins and the table's creator get the highest level before
        any rule is read, so the move can't change their access.
        """
        scopes: dict[_Scope, tuple[SourceRule, ...]] = {
            "table": table_rules,
            "warehouse": self._warehouse,
            "sources": self._sources,
            "source": source_rules,
        }
        defaults = {
            scope: [_Row(level=rule.access_level, subject="default") for rule in rules if rule.subject == "default"]
            for scope, rules in scopes.items()
        }
        role_profiles = [profile for profile in _profiles(scopes, "role") if profile != _EMPTY_PROFILE]
        if len(role_profiles) > _MAX_ROLE_PROFILES:
            return ROLES_REASON
        for member_profile in _profiles(scopes, "member"):
            for count in range(len(role_profiles) + 1):
                for roles in itertools.combinations(role_profiles, count):
                    rows = {
                        scope: [
                            *defaults[scope],
                            *(
                                [_Row(level=member_level, subject="member")]
                                if (member_level := member_profile[i])
                                else []
                            ),
                            *(_Row(level=level, subject="role") for role in roles if (level := role[i]) is not None),
                        ]
                        for i, scope in enumerate(_SCOPES)
                    }
                    for resolve in (_legacy_level, _most_specific_level):
                        before = resolve(rows["table"], None, rows["warehouse"], rows["sources"])
                        after = resolve(rows["table"], rows["source"], rows["warehouse"], rows["sources"])
                        source = resolve(rows["source"], None, rows["sources"], ())
                        if after != before or _rank(source) > _rank(before):
                            return False
        return True


_Profile = tuple[str | None, ...]
_EMPTY_PROFILE: _Profile = (None, None, None, None)


def _profiles(scopes: dict[_Scope, tuple[SourceRule, ...]], subject: Literal["member", "role"]) -> list[_Profile]:
    """The level each subject of one kind has in each scope, once per distinct set of levels.

    Subjects with the same levels resolve the same, so each set is checked once. The empty set stands
    for a member that no rule names, or for having no role.
    """
    levels: dict[str, dict[_Scope, str]] = defaultdict(dict)
    for scope, rules in scopes.items():
        for rule in rules:
            if rule.subject == subject:
                subject_id = rule.organization_member_id if subject == "member" else rule.role_id
                assert subject_id is not None
                levels[subject_id][scope] = rule.access_level
    profiles = {tuple(by_scope.get(scope) for scope in _SCOPES) for by_scope in levels.values()}
    profiles.add(_EMPTY_PROFILE)
    return sorted(profiles, key=repr)


def _subject_rules(rules: Iterable[AccessRule]) -> tuple[SourceRule, ...]:
    highest: dict[tuple[str | None, str | None], str] = {}
    for rule in rules:
        key = (
            str(rule.organization_member_id) if rule.organization_member_id else None,
            str(rule.role_id) if rule.role_id else None,
        )
        current, level = highest.get(key), rule.access_level
        # An unknown level is kept, so the plan refuses the table instead of guessing what it means.
        if current is None or level not in LEVELS or (current in LEVELS and _rank(level) > _rank(current)):
            highest[key] = level
    return _sorted(
        SourceRule(access_level=level, organization_member_id=member_id, role_id=role_id)
        for (member_id, role_id), level in highest.items()
    )


def _sorted(rules: Iterable[SourceRule]) -> tuple[SourceRule, ...]:
    return tuple(
        sorted(
            rules,
            key=lambda r: (_SUBJECTS.index(r.subject), r.organization_member_id or "", r.role_id or "", r.access_level),
        )
    )


def write_source_rules(team_id: int, source_id: str, plan: SourceAccessPlan) -> None:
    replace_object_access_rules(
        team_id=team_id,
        resource=SOURCE_RESOURCE,
        resource_id=source_id,
        rules=[
            ObjectAccessRuleInput(
                access_level=rule.access_level,
                organization_member_id=UUID(rule.organization_member_id) if rule.organization_member_id else None,
                role_id=UUID(rule.role_id) if rule.role_id else None,
            )
            for rule in plan.rules
        ],
    )


def remove_source_rules(team_id: int, source_id: str) -> None:
    replace_object_access_rules(team_id=team_id, resource=SOURCE_RESOURCE, resource_id=source_id, rules=[])


def adoption_access_refusal(
    table: DataWarehouseTable, source: ExternalDataSource, rules: TeamAccessRules | None = None
) -> str | None:
    """Why the source must not adopt the table now, or None when the move keeps everyone's access.

    The rules may have changed since the migration linked the table: on the table, on the source, or
    for the whole warehouse or all sources. The source's rules must still be the ones the table needs.
    """
    rules = rules or TeamAccessRules(table.team_id)
    planned = rules.plan_for(str(table.id))
    if isinstance(planned, str):
        return f"the access rules changed after the migration, and now {planned}"
    if rules.source_rules(str(source.pk)) != planned.rules:
        return "the access rules of the table or of its source changed after the migration"
    return None


def adoption_access_error(table: DataWarehouseTable, source: ExternalDataSource) -> str | None:
    """The error to show when a migration source must not adopt the table, or None when it may.

    Sources the migration didn't make are not checked.
    """
    if MIGRATION_MARKER_KEY not in (source.connection_metadata or {}):
        return None
    refusal = adoption_access_refusal(table, source)
    if refusal is None:
        return None
    return (
        f"{ADOPTION_ACCESS_ERROR} '{table.name}', because {refusal}. The table still reads its own files. "
        "To continue, an organization admin must make the access rules of this source the same as the "
        "rules of the table, then turn syncing on again. PostHog support can help with this."
    )


def assert_adoption_keeps_access(table: DataWarehouseTable, source: ExternalDataSource) -> None:
    error = adoption_access_error(table, source)
    if error is not None:
        raise AdoptionAccessError(error)
