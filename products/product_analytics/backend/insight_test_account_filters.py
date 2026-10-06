import copy
from typing import Any

from pydantic import BaseModel

from posthog import schema
from posthog.dataclasses import frozen
from posthog.hogql_queries.apply_dashboard_filters import WRAPPER_NODE_KINDS

_WRAPPER_KINDS = {kind.value for kind in WRAPPER_NODE_KINDS}


def _kinds_supporting(field: str) -> frozenset[str]:
    """Read the query kinds that carry `field` off the generated schema, so a kind that gains
    the field is covered without anyone remembering to update a hardcoded list."""
    kinds: set[str] = set()
    for candidate in vars(schema).values():
        if not (isinstance(candidate, type) and issubclass(candidate, BaseModel)):
            continue
        fields = candidate.model_fields
        if field not in fields or "kind" not in fields:
            continue
        kind = getattr(fields["kind"].default, "value", fields["kind"].default)
        if isinstance(kind, str):
            kinds.add(kind)
    return frozenset(kinds)


TEST_ACCOUNT_FILTER_FIELD = "filterTestAccounts"
DEFAULT_FILTERS_FIELD = "applyDefaultFilters"

KINDS_SUPPORTING_TEST_ACCOUNT_FILTER = _kinds_supporting(TEST_ACCOUNT_FILTER_FIELD)
KINDS_SUPPORTING_DEFAULT_FILTERS = _kinds_supporting(DEFAULT_FILTERS_FIELD)


@frozen
class TestAccountFilterUpdate:
    """What setting the test account filter to a given value would do to one insight."""

    supported: bool
    query: dict[str, Any] | None = None

    @property
    def changed(self) -> bool:
        return self.query is not None


UNSUPPORTED = TestAccountFilterUpdate(supported=False)
ALREADY_SET = TestAccountFilterUpdate(supported=True)


def _plan_flag_update(query: Any, *, field: str, kinds: frozenset[str], enabled: bool) -> TestAccountFilterUpdate:
    if not isinstance(query, dict):
        return UNSUPPORTED

    node = query
    while node.get("kind") in _WRAPPER_KINDS and isinstance(node.get("source"), dict):
        node = node["source"]
    if node.get("kind") not in kinds:
        return UNSUPPORTED
    if bool(node.get(field)) == enabled:
        return ALREADY_SET

    updated = copy.deepcopy(query)
    target = updated
    while target.get("kind") in _WRAPPER_KINDS and isinstance(target.get("source"), dict):
        target = target["source"]
    target[field] = enabled
    return TestAccountFilterUpdate(supported=True, query=updated)


def plan_test_account_filter_update(query: Any, *, enabled: bool) -> TestAccountFilterUpdate:
    """Work out how to set the test account filter on an insight, without touching the stored query.

    `supported` is False for insights with nowhere to put the toggle, such as SQL insights. When it is True
    but nothing changed, the insight already had this value.
    """
    return _plan_flag_update(
        query, field=TEST_ACCOUNT_FILTER_FIELD, kinds=KINDS_SUPPORTING_TEST_ACCOUNT_FILTER, enabled=enabled
    )


def plan_default_filters_update(query: Any, *, enabled: bool) -> TestAccountFilterUpdate:
    """Same as `plan_test_account_filter_update`, for the `applyDefaultFilters` flag."""
    return _plan_flag_update(
        query, field=DEFAULT_FILTERS_FIELD, kinds=KINDS_SUPPORTING_DEFAULT_FILTERS, enabled=enabled
    )
