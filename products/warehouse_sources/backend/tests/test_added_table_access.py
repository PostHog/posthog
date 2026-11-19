from uuid import UUID, uuid4

import pytest
from unittest.mock import patch

from products.access_control.backend.facade.contracts import AccessRule
from products.warehouse_sources.backend.self_managed_access import LEVELS, TeamAccessRules

TABLE_ID = "11111111-1111-1111-1111-111111111111"
TABLE_SOURCE_ID = "22222222-2222-2222-2222-222222222222"
ADDED_SOURCE_ID = "33333333-3333-3333-3333-333333333333"
MEMBER = UUID("44444444-4444-4444-4444-444444444444")
ROLE = UUID("55555555-5555-5555-5555-555555555555")

_RESOURCES = {
    "table": ("warehouse_table", TABLE_ID),
    "table_source": ("external_data_source", TABLE_SOURCE_ID),
    "added_source": ("external_data_source", ADDED_SOURCE_ID),
    "warehouse": ("warehouse_objects", None),
}


def _rule(scope: str, level: str, member: UUID | None = None, role: UUID | None = None) -> AccessRule:
    resource, resource_id = _RESOURCES[scope]
    return AccessRule(
        resource=resource,
        resource_id=resource_id,
        access_level=level,
        organization_member_id=member,
        role_id=role,
        applies=True,
    )


@pytest.mark.parametrize(
    "rules, table_source_id, widens",
    [
        pytest.param([], TABLE_SOURCE_ID, False, id="no_rules"),
        pytest.param([_rule("table", "none")], TABLE_SOURCE_ID, True, id="table_hidden_from_everyone"),
        pytest.param(
            [_rule("table", "none"), _rule("table", "viewer", member=MEMBER)],
            TABLE_SOURCE_ID,
            True,
            id="table_shown_only_to_one_member",
        ),
        pytest.param(
            [_rule("table", "none"), _rule("added_source", "none")],
            TABLE_SOURCE_ID,
            False,
            id="added_source_hides_as_much_as_the_table",
        ),
        pytest.param(
            [_rule("table", "viewer", role=ROLE), _rule("added_source", "editor", role=ROLE)],
            TABLE_SOURCE_ID,
            True,
            id="added_source_gives_a_role_more",
        ),
        pytest.param(
            [_rule("table_source", "none")],
            TABLE_SOURCE_ID,
            True,
            id="sibling_source_hides_its_tables",
        ),
        pytest.param([_rule("table", "none")], None, True, id="self_managed_table_hidden"),
        pytest.param(
            [_rule("table", "none"), _rule("added_source", "none")],
            None,
            False,
            id="self_managed_table_and_added_source_both_hidden",
        ),
        pytest.param([_rule("warehouse", "none")], TABLE_SOURCE_ID, False, id="warehouse_rule_applies_to_both"),
        pytest.param([_rule("table", "owner")], TABLE_SOURCE_ID, True, id="unknown_level_is_refused"),
    ],
)
def test_an_added_table_must_not_show_more_than_the_table_whose_files_it_reads(
    rules: list[AccessRule], table_source_id: str | None, widens: bool
) -> None:
    with patch("products.warehouse_sources.backend.self_managed_access.access_rules", return_value=rules):
        team_rules = TeamAccessRules(team_id=1)

    assert team_rules.added_table_widens_access(TABLE_ID, table_source_id, ADDED_SOURCE_ID) is widens


def _hidden_in_added_source(count: int, member: bool) -> list[AccessRule]:
    """Subjects with distinct levels, each hidden from the added source, so no subject gets more access from it."""
    rules: list[AccessRule] = []
    for index in range(count):
        subject = {"member": uuid4()} if member else {"role": uuid4()}
        rules += [
            _rule("table", LEVELS[index % 4], **subject),
            _rule("table_source", LEVELS[(index // 4) % 4], **subject),
            _rule("warehouse", LEVELS[(index // 16) % 4], **subject),
            _rule("added_source", "none", **subject),
        ]
    return rules


@pytest.mark.parametrize(
    "rules, budget_spent",
    [
        pytest.param(_hidden_in_added_source(11, member=False), False, id="more_role_profiles_than_the_cap"),
        pytest.param(
            [*_hidden_in_added_source(10, member=False), *_hidden_in_added_source(40, member=True)],
            True,
            id="more_combinations_than_the_budget",
        ),
    ],
)
def test_rules_too_many_to_check_are_refused(rules: list[AccessRule], budget_spent: bool) -> None:
    with patch("products.warehouse_sources.backend.self_managed_access.access_rules", return_value=rules):
        team_rules = TeamAccessRules(team_id=1)

    assert team_rules.added_table_widens_access(TABLE_ID, TABLE_SOURCE_ID, ADDED_SOURCE_ID) is True
    assert team_rules.added_table_budget_spent is budget_spent


def test_rules_under_the_limits_that_hide_the_added_source_are_allowed() -> None:
    rules = [*_hidden_in_added_source(10, member=False), *_hidden_in_added_source(5, member=True)]
    with patch("products.warehouse_sources.backend.self_managed_access.access_rules", return_value=rules):
        team_rules = TeamAccessRules(team_id=1)

    assert team_rules.added_table_widens_access(TABLE_ID, TABLE_SOURCE_ID, ADDED_SOURCE_ID) is False
