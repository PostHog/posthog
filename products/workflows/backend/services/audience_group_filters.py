"""Group property conditions in a person audience.

A person audience compiles to a filter over `persons`, and `persons` holds no link to groups. A
group property condition matches the persons that the person-to-group membership records in a
group with that property. Membership is recorded only for the customer analytics account group
type, so a condition on another group type is rejected instead of being dropped, because a
dropped condition sends to a wider audience.
"""

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Optional

from rest_framework import exceptions

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.person_group_membership import PersonGroupMembershipTable
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr

from posthog.models.property import Property, PropertyGroup, PropertyOperatorType
from posthog.models.property.property import PropertyValidationError
from posthog.models.team.team import Team

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.feature_flags.backend.person_sampling import sample_predicate
from products.workflows.backend.facade.contracts import PersonGroupMembership
from products.workflows.backend.services.account_audience import get_person_group_membership

if TYPE_CHECKING:
    from posthog.models.user import User

GROUP_TYPE_NOT_SUPPORTED_MESSAGE = (
    "People can only be filtered by properties of the account group type set in customer analytics."
)
MEMBERSHIP_NOT_READY_MESSAGE = "Account membership is still being calculated. Try again when it finishes."
INVALID_GROUP_CONDITION_MESSAGE = (
    "A group property condition is incomplete or invalid. Check its property, group type, and value."
)
TEST_ACCOUNT_GROUP_TYPE_MESSAGE = (
    "Your test account filters use a group type other than accounts, so they can't be combined with account "
    "properties. Turn off test account filtering for this audience, or change those filters."
)


def audience_group_type_index(team: Team, filters: dict) -> Optional[int]:
    """The group type that the audience's group property conditions read, or None when it has none."""
    membership = _supported_membership(team, filters)
    if membership is None:
        return None
    # A backfill in progress holds only part of the membership, so a send would silently miss people.
    if not membership.ready:
        raise exceptions.ValidationError({"filters": MEMBERSHIP_NOT_READY_MESSAGE})
    return membership.group_type_index


def reject_unsupported_group_conditions_in_audience(team: Team, filters: dict, user: Optional["User"] = None) -> None:
    # Readiness is checked when the audience is sized or sent, so a membership backfill doesn't block edits.
    membership = _supported_membership(team, filters)
    if membership is None or user is None or not user.is_authenticated:
        return
    # Neither the audience count nor the send applies a member's own rules to group properties, so a
    # member denied one could otherwise learn its values from the count or from who the batch reaches.
    restricted = {
        restriction.name
        for restriction in get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk)
        if restriction.group_type_index == membership.group_type_index
    }
    for condition in _group_conditions(filters):
        if condition.get("key") in restricted:
            raise exceptions.ValidationError(
                {
                    "filters": f'You don\'t have access to the account property "{condition["key"]}". '
                    "Remove it from the audience, or ask an admin for access."
                }
            )


def _supported_membership(team: Team, filters: dict) -> Optional[PersonGroupMembership]:
    # This reads the raw filters because the parser drops a condition it can't parse, such as one with no
    # value or an invalid group_type_index, and the audience would then silently lose that condition.
    conditions = _group_conditions(filters)
    if not conditions:
        return None
    for condition in conditions:
        try:
            Property(**condition)
        except (PropertyValidationError, exceptions.ValidationError, TypeError):
            raise exceptions.ValidationError({"filters": INVALID_GROUP_CONDITION_MESSAGE})
    indices = {condition.get("group_type_index") for condition in conditions}
    membership = get_person_group_membership(team)
    if membership is None or indices != {membership.group_type_index}:
        raise exceptions.ValidationError({"filters": GROUP_TYPE_NOT_SUPPORTED_MESSAGE})
    return membership


def _group_conditions(filters: dict) -> list[dict]:
    return [
        condition
        for condition in _raw_conditions((filters or {}).get("properties"))
        if condition.get("type") == "group"
    ]


def _raw_conditions(node: object) -> Iterator[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _raw_conditions(item)
    elif isinstance(node, dict):
        if isinstance(node.get("values"), list):
            yield from _raw_conditions(node["values"])
        else:
            yield node


def audience_query_context(
    team: Team, group_type_index: Optional[int], database: Optional[Database] = None
) -> HogQLContext:
    # HogQL reads the group type from this global to resolve the types of group properties that a
    # query reads from `groups` directly. Without it, a Boolean group property compares as a string.
    return HogQLContext(
        team_id=team.pk,
        database=database,
        globals={"group_id": group_type_index} if group_type_index is not None else None,
    )


def person_audience_filter_expr(
    team: Team,
    prop_group: PropertyGroup,
    group_type_index: Optional[int],
    *,
    sample_modulus: Optional[int] = None,
    cursor: Optional[str] = None,
) -> ast.Expr:
    """`sample_modulus` and `cursor` must match the outer query's own person sample and cursor. They only
    narrow which persons the group membership resolves to, so it doesn't build the whole audience per query."""
    if group_type_index is None:
        return property_to_expr(prop_group, team, scope="person")

    # Each group condition gets its own nodes, because HogQL resolves types onto the nodes in place.
    def member_constraints() -> list[ast.Expr]:
        constraints: list[ast.Expr] = []
        if sample_modulus is not None:
            constraints.append(sample_predicate(_member_person_id(), sample_modulus))
        if cursor is not None:
            constraints.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt, left=_member_person_id(), right=ast.Constant(value=cursor)
                )
            )
        return constraints

    return _filter_expr(team, prop_group, group_type_index, member_constraints)


def _filter_expr(
    team: Team, node: PropertyGroup | Property, group_type_index: int, member_constraints: Callable[[], list[ast.Expr]]
) -> ast.Expr:
    if isinstance(node, PropertyGroup):
        exprs = [_filter_expr(team, value, group_type_index, member_constraints) for value in node.values]
        if not exprs:
            return ast.Constant(value=1)
        if len(exprs) == 1:
            return exprs[0]
        return ast.And(exprs=exprs) if node.type == PropertyOperatorType.AND else ast.Or(exprs=exprs)
    if node.type == "group":
        # The audience's own conditions are checked before this, but test account filters are expanded
        # into the filter later, and membership holds only the account group type.
        if node.group_type_index != group_type_index:
            raise exceptions.ValidationError({"filters": TEST_ACCOUNT_GROUP_TYPE_MESSAGE})
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["persons", "id"]),
            right=_group_members_query(team, node, group_type_index, member_constraints),
        )
    return property_to_expr(node, team, scope="person")


def _member_person_id() -> ast.Expr:
    # The HAVING reads the `person_id` alias of the select. Repeating `argMax(person_id, version)` there
    # resolves its inner `person_id` to that alias too, and ClickHouse rejects the nested aggregate.
    return ast.Field(chain=["person_id"])


def _group_members_query(
    team: Team, prop: Property, group_type_index: int, member_constraints: Callable[[], list[ast.Expr]]
) -> ast.SelectQuery:
    matching_groups = ast.SelectQuery(
        select=[ast.Field(chain=["groups", "key"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["groups", "index"]),
                    right=ast.Constant(value=group_type_index),
                ),
                property_to_expr(prop, team, scope="group"),
            ]
        ),
    )
    members = ast.SelectQuery(
        select=[ast.Field(chain=["distinct_id"])],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=["posthog", "person_group_membership"]),
            table_schema=PersonGroupMembershipTable(),
        ),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["group_type_index"]),
                    right=ast.Constant(value=group_type_index),
                ),
                # The membership table is distributed over a cluster that does not hold `groups`, so the
                # initiator resolves the matching group keys and ships them to the shards.
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GlobalIn,
                    left=ast.Field(chain=["group_key"]),
                    right=matching_groups,
                ),
            ]
        ),
    )
    query = parse_select(
        """
        SELECT argMax(person_id, version) AS person_id
        FROM raw_person_distinct_ids
        WHERE distinct_id IN {members}
        GROUP BY distinct_id
        HAVING {having}
        """,
        placeholders={
            "members": members,
            "having": ast.And(exprs=[parse_expr("argMax(is_deleted, version) = 0"), *member_constraints()]),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query
