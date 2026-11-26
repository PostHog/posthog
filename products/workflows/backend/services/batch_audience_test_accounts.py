from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.models.property.parse import parse_property_group_data
from posthog.models.team.team import Team

# Every other type stays in the audience. A person or cohort filter that can't be evaluated must fail the run, because
# leaving it out would message the people it excludes.
_EVENT_ONLY_FILTER_TYPES = {"event", "event_metadata", "element", "feature", "group", "session"}


class _PersonFieldFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found: list[ast.Field] = []
        self._lambda_args: set[str] = set()

    def visit_field(self, node: ast.Field) -> None:
        root = node.chain[0]
        if root in self._lambda_args:
            return
        if node.chain == ["person_id"] or (root == "person" and len(node.chain) > 1):
            self.found.append(node)

    def visit_lambda(self, node: ast.Lambda) -> None:
        outer = self._lambda_args
        self._lambda_args = outer | set(node.args)
        super().visit_lambda(node)
        self._lambda_args = outer

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A subquery reads its own tables, where these names mean something else.
        pass

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass


def _for_persons(test_filter: dict[str, Any]) -> dict[str, Any]:
    """SQL test account filters are written for events, where the person is `person` and its id is `person_id`."""
    if test_filter.get("type") != "hogql":
        return test_filter
    sql = str(test_filter.get("key"))
    finder = _PersonFieldFinder()
    finder.visit(parse_expr(sql))
    # Only the names change in the text. Printing the rewritten AST turns a regex operator into a plain `match` call,
    # which treats a missing value differently and so changes who the filter excludes.
    for node in sorted(finder.found, key=lambda field: field.start or 0, reverse=True):
        name = sql[node.start : node.end]
        on_persons = "persons.id" if node.chain == ["person_id"] else "persons" + name[name.index(".") :]
        sql = sql[: node.start] + on_persons + sql[node.end :]
    return {**test_filter, "key": sql}


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
        event_only = (test_filter.get("type") or "event") in _EVENT_ONLY_FILTER_TYPES
        (skipped if event_only else applicable).append(test_filter)
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
    test_accounts = {"type": "AND", "values": [_for_persons(test_filter) for test_filter in applicable]}
    existing = parse_property_group_data(filters.get("properties")).to_dict()
    folded["properties"] = {"type": "AND", "values": [test_accounts, existing]} if existing else test_accounts
    return folded


def skipped_test_account_filter_keys(team: Team, filters: object) -> list[str]:
    """The keys of the test account filters a batch audience leaves out, so the editor and the run log can name them."""
    if not _wants_test_account_filters(filters):
        return []
    return [str(test_filter.get("key")) for test_filter in _split_test_account_filters(team).skipped]
