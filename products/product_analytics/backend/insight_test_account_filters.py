import copy
from typing import Any

from pydantic import BaseModel

from posthog import schema
from posthog.dataclasses import frozen
from posthog.hogql_queries.apply_dashboard_filters import WRAPPER_NODE_KINDS

_WRAPPER_KINDS = {kind.value for kind in WRAPPER_NODE_KINDS}


def _kinds_supporting_test_account_filter() -> frozenset[str]:
    """Read the query kinds that carry `filterTestAccounts` off the generated schema, so a kind that gains
    the field is covered without anyone remembering to update a hardcoded list."""
    kinds: set[str] = set()
    for candidate in vars(schema).values():
        if not (isinstance(candidate, type) and issubclass(candidate, BaseModel)):
            continue
        fields = candidate.model_fields
        if "filterTestAccounts" not in fields or "kind" not in fields:
            continue
        kind = getattr(fields["kind"].default, "value", fields["kind"].default)
        if isinstance(kind, str):
            kinds.add(kind)
    return frozenset(kinds)


KINDS_SUPPORTING_TEST_ACCOUNT_FILTER = _kinds_supporting_test_account_filter()


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


def plan_test_account_filter_update(query: Any, *, enabled: bool) -> TestAccountFilterUpdate:
    """Work out how to set the test account filter on an insight, without touching the stored query.

    `supported` is False for insights with nowhere to put the toggle, such as SQL insights. When it is True
    but nothing changed, the insight already had this value.
    """
    if not isinstance(query, dict):
        return UNSUPPORTED

    node = query
    while node.get("kind") in _WRAPPER_KINDS and isinstance(node.get("source"), dict):
        node = node["source"]
    if node.get("kind") not in KINDS_SUPPORTING_TEST_ACCOUNT_FILTER:
        return UNSUPPORTED
    if bool(node.get("filterTestAccounts")) == enabled:
        return ALREADY_SET

    updated = copy.deepcopy(query)
    target = updated
    while target.get("kind") in _WRAPPER_KINDS and isinstance(target.get("source"), dict):
        target = target["source"]
    target["filterTestAccounts"] = enabled
    return TestAccountFilterUpdate(supported=True, query=updated)
