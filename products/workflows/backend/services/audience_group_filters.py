"""Group property conditions in a person audience.

A person audience compiles to a filter over `persons`, and `persons` holds no link to groups. A
group property condition matches the persons that the person-to-group membership records in a
group with that property. Membership is recorded only for the customer analytics account group
type, so a condition on another group type is rejected instead of being dropped, because a
dropped condition sends to a wider audience.
"""

from typing import Optional

from rest_framework import exceptions

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.person_group_membership import PersonGroupMembershipTable
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.models.property import Property, PropertyGroup, PropertyOperatorType
from posthog.models.property.parse import parse_property_group_data
from posthog.models.team.team import Team

from products.workflows.backend.facade.contracts import PersonGroupMembership
from products.workflows.backend.services.account_audience import get_person_group_membership

GROUP_TYPE_NOT_SUPPORTED_MESSAGE = (
    "People can only be filtered by properties of the account group type set in customer analytics."
)
MEMBERSHIP_NOT_READY_MESSAGE = "Account membership is still being calculated. Try again when it finishes."


def audience_group_type_index(team: Team, prop_group: PropertyGroup) -> Optional[int]:
    """The group type that the audience's group property conditions read, or None when it has none."""
    membership = _supported_membership(team, prop_group)
    if membership is None:
        return None
    # A backfill in progress holds only part of the membership, so a send would silently miss people.
    if not membership.ready:
        raise exceptions.ValidationError({"filters": MEMBERSHIP_NOT_READY_MESSAGE})
    return membership.group_type_index


def reject_unsupported_group_conditions_in_audience(team: Team, filters: dict) -> None:
    # Readiness is checked when the audience is sized or sent, so a membership backfill doesn't block edits.
    try:
        prop_group = parse_property_group_data((filters or {}).get("properties"))
    except (ValueError, exceptions.ValidationError):
        # Malformed properties fail when the audience is sized, with the message that sizing gives.
        return
    _supported_membership(team, prop_group)


def _supported_membership(team: Team, prop_group: PropertyGroup) -> Optional[PersonGroupMembership]:
    indices = {prop.group_type_index for prop in prop_group.flat if prop.type == "group"}
    if not indices:
        return None
    membership = get_person_group_membership(team)
    if membership is None or indices != {membership.group_type_index}:
        raise exceptions.ValidationError({"filters": GROUP_TYPE_NOT_SUPPORTED_MESSAGE})
    return membership


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


def person_audience_filter_expr(team: Team, prop_group: PropertyGroup, group_type_index: Optional[int]) -> ast.Expr:
    if group_type_index is None:
        return property_to_expr(prop_group, team, scope="person")
    return _filter_expr(team, prop_group, group_type_index)


def _filter_expr(team: Team, node: PropertyGroup | Property, group_type_index: int) -> ast.Expr:
    if isinstance(node, PropertyGroup):
        exprs = [_filter_expr(team, value, group_type_index) for value in node.values]
        if not exprs:
            return ast.Constant(value=1)
        if len(exprs) == 1:
            return exprs[0]
        return ast.And(exprs=exprs) if node.type == PropertyOperatorType.AND else ast.Or(exprs=exprs)
    if node.type == "group":
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["persons", "id"]),
            right=_group_members_query(team, node, group_type_index),
        )
    return property_to_expr(node, team, scope="person")


def _group_members_query(team: Team, prop: Property, group_type_index: int) -> ast.SelectQuery:
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
    # Membership records distinct ids, so each one resolves to its current person. A distinct id
    # that has moved to another person since the membership was written follows the person.
    query = parse_select(
        """
        SELECT argMax(person_id, version) AS person_id
        FROM raw_person_distinct_ids
        WHERE distinct_id IN {members}
        GROUP BY distinct_id
        HAVING argMax(is_deleted, version) = 0
        """,
        placeholders={"members": members},
    )
    assert isinstance(query, ast.SelectQuery)
    return query
