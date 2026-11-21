from typing import Any

from posthog.hogql.errors import (
    NotImplementedError as HogQLNotImplementedError,
    QueryError,
)
from posthog.hogql.property import property_to_expr

from posthog.dataclasses import frozen
from posthog.models.property.parse import parse_property_group_data
from posthog.models.team.team import Team


def _wants_test_account_filters(filters: object) -> bool:
    return isinstance(filters, dict) and filters.get("filter_test_accounts") in (True, "true")


@frozen
class _SplitTestAccountFilters:
    applicable: list[dict[str, Any]]
    skipped: list[dict[str, Any]]


def _split_test_account_filters(team: Team) -> _SplitTestAccountFilters:
    """The project's test account filters a person audience can apply, and the ones it can't, such as event properties."""
    applicable: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for test_filter in team.test_account_filters or []:
        try:
            property_to_expr(test_filter, team, scope="person")
        except (QueryError, HogQLNotImplementedError):
            skipped.append(test_filter)
        else:
            applicable.append(test_filter)
    return _SplitTestAccountFilters(applicable=applicable, skipped=skipped)


def with_person_test_account_filters(team: Team, filters: dict) -> dict:
    """
    The audience filters with the project's test account filters folded in, leaving out the ones that only apply to
    events. A batch audience is a list of persons, so an event filter there would fail the whole run.
    """
    if not _wants_test_account_filters(filters):
        return filters
    applicable = _split_test_account_filters(team).applicable
    folded = {**filters, "filter_test_accounts": False}
    if not applicable:
        return folded
    test_accounts = {"type": "AND", "values": applicable}
    existing = parse_property_group_data(filters.get("properties")).to_dict()
    folded["properties"] = {"type": "AND", "values": [test_accounts, existing]} if existing else test_accounts
    return folded


def skipped_test_account_filter_keys(team: Team, filters: object) -> list[str]:
    """The keys of the test account filters a batch audience leaves out, so the editor and the run log can name them."""
    if not _wants_test_account_filters(filters):
        return []
    return [str(test_filter.get("key")) for test_filter in _split_test_account_filters(team).skipped]
