import datetime as dt

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import RecordingsQuery

from posthog.hogql import ast

from posthog.clickhouse.query_tagging import Product, get_query_tags
from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_scanner import SETTLE_INTERVAL
from products.replay_vision.backend.queries.scanner_candidate_query import (
    CandidateSession,
    ScannerCandidateQuery,
    build_candidate_batch,
    run_correlated_batch,
    session_in_predicates,
)

_T0 = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_SCANNER_ID = "0199aaaa-bbbb-7ccc-8ddd-eeeeffff0000"


def _sessions(count: int, prefix: str = "s") -> list[CandidateSession]:
    return [
        CandidateSession(session_id=f"{prefix}-{i}", session_end=_T0 + dt.timedelta(seconds=i)) for i in range(count)
    ]


def _group_column_bounds(node: ast.Expr | ast.SelectQuery | None) -> list[str] | None:
    if node is None:
        return None
    if (
        isinstance(node, ast.CompareOperation)
        and node.op == ast.CompareOperationOp.In
        and isinstance(node.left, ast.Field)
        and str(node.left.chain[-1]).startswith("$group_")
        and isinstance(node.right, ast.Constant)
    ):
        return list(node.right.value)
    for child in _children(node):
        found = _group_column_bounds(child)
        if found is not None:
            return found
    return None


def _children(node: ast.Expr | ast.SelectQuery) -> list:
    if isinstance(node, ast.SelectQuery):
        return [node.where, node.having, node.select_from, *(node.select or [])]
    if isinstance(node, ast.JoinExpr):
        return [node.table, node.constraint, node.next_join]
    if isinstance(node, ast.JoinConstraint):
        return [node.expr]
    if isinstance(node, ast.CompareOperation):
        return [node.left, node.right]
    if isinstance(node, ast.Call):
        return list(node.args or [])
    return list(getattr(node, "exprs", None) or [])


def _bounds_sessions(node: ast.Expr | None) -> bool:
    """Whether the outer query restricts `sessions.session_id` to a fixed list."""
    if node is None:
        return False
    if (
        isinstance(node, ast.CompareOperation)
        and node.op == ast.CompareOperationOp.In
        and isinstance(node.left, ast.Field)
        and node.left.chain[-1] == "session_id"
        and isinstance(node.right, ast.Constant)
    ):
        return True
    return any(_bounds_sessions(e) for e in (getattr(node, "exprs", None) or []))


class TestBuildCandidateBatch:
    @parameterized.expand(
        [
            # Fewer matches than room to dispatch: the walk covered every candidate, so it may move
            # past the ones that did not match. Stopping at the last match would re-walk them forever.
            ("all_matches_fit", 10, 3, 20, 100, 3, "s-9", False),
            # More matches than room: everything past the last dispatched one is unexamined ground.
            # Advancing to the last candidate here would drop matched sessions permanently.
            ("more_matches_than_room", 50, 40, 10, 100, 10, "m-9", True),
            # Candidate scan hit its own cap, so more sessions wait past the keyset.
            ("candidate_scan_saturated", 100, 2, 20, 100, 2, "s-99", True),
            ("nothing_matched", 10, 0, 20, 100, 0, "s-9", False),
        ]
    )
    def test_keyset_stops_where_the_tick_stopped(
        self,
        _name: str,
        considered_count: int,
        matched_count: int,
        dispatch_limit: int,
        scan_limit: int,
        expected_dispatched: int,
        expected_keyset_id: str,
        expected_saturated: bool,
    ) -> None:
        considered = _sessions(considered_count, "s")
        matched = _sessions(matched_count, "m")

        batch = build_candidate_batch(considered, matched, dispatch_limit, scan_limit)

        assert len(batch.matched) == expected_dispatched
        assert batch.keyset_session_id == expected_keyset_id
        assert batch.saturated is expected_saturated

    def test_no_candidates_leaves_the_watermark_alone(self) -> None:
        batch = build_candidate_batch([], [], 20, 100)

        assert batch.keyset_end is None
        assert batch.keyset_session_id == ""


@pytest.mark.django_db
class TestSessionInPredicates:
    def _query(
        self,
        *,
        filter_test_accounts: bool,
        with_event_filter: bool,
        operand: str = "AND",
        group_filter: bool = False,
    ) -> ScannerCandidateQuery:
        org = Organization.objects.create(name="predicate-test-org")
        team = Team.objects.create(
            organization=org,
            name="predicate-test-team",
            test_account_filters=[
                {"key": "$host", "type": "event", "value": "app.example.com", "operator": "icontains"}
            ],
        )
        query: dict = {"kind": "RecordingsQuery", "filter_test_accounts": filter_test_accounts, "operand": operand}
        properties: list[dict] = []
        if with_event_filter:
            properties.append({"key": "plan", "type": "event", "value": "pro", "operator": "exact"})
        if group_filter:
            properties.append(
                {
                    "key": "owner",
                    "type": "group",
                    "value": ["a@example.com"],
                    "operator": "exact",
                    "group_type_index": 0,
                }
            )
        if properties:
            query["properties"] = properties
        return ScannerCandidateQuery(
            team=team,
            query=RecordingsQuery.model_validate(query),
            last_swept_at=dt.datetime.now(dt.UTC) - SETTLE_INTERVAL - dt.timedelta(minutes=10),
            sampling_rate=1.0,
            sampling_salt="salt",
            events_lookback=dt.timedelta(hours=4),
            skip_negative_blocklists=True,
            scanner_id=_SCANNER_ID,
        )

    def test_finds_the_test_account_subquery_as_well_as_the_scanners_own(self) -> None:
        # Test-account filters compile to a second events subquery. Restricting only the first leaves
        # the other scanning the whole events window, which silently costs the entire saving.
        predicates = session_in_predicates(self._query(filter_test_accounts=True, with_event_filter=True).get_query())

        assert len(predicates) == 2

    def test_an_or_filter_still_bounds_the_match_query_to_the_scanned_page(self) -> None:
        # With operand OR a session can match through a non-event branch, which the subquery
        # restriction never sees. Without the outer bound the match set runs past the page the
        # keyset is computed from, so the walk advances over sessions it never correlated.
        candidate_query = self._query(filter_test_accounts=False, with_event_filter=True, operand="OR")
        executed: list[ast.SelectQuery] = []

        def execute(query: ast.SelectQuery, query_type: str) -> list[CandidateSession]:
            executed.append(query)
            return [CandidateSession(session_id="sess-a", session_end=_T0)] if len(executed) == 1 else []

        run_correlated_batch(
            build=candidate_query.get_query,
            execute=execute,
            scan_query_type="scan",
            match_query_type="match",
            dispatch_limit=10,
        )

        assert _bounds_sessions(executed[1].where)

    def test_a_group_filter_is_resolved_to_the_group_column(self) -> None:
        # Joining the groups table makes every ClickHouse shard scan it independently, so a sweep
        # tick pays that scan once per shard. Filtering on the resolved keys instead is the whole
        # point of the opt-in, and losing it anywhere in the plumbing is invisible without this.
        query = self._query(filter_test_accounts=False, with_event_filter=False, group_filter=True)
        with patch(
            "posthog.session_recordings.queries.sub_queries.group_key_resolver._query_group_keys",
            return_value=["org-1"],
        ):
            built = query.get_query()

        assert _group_column_bounds(built) == ["org-1"]

    def test_the_group_resolution_read_is_attributable_to_the_scanner(self) -> None:
        # The read meter only counts query-log rows carrying this product and a scanner id. Untag the
        # build and the resolution spends silently, so the sweep throttle never charges it.
        query = self._query(filter_test_accounts=False, with_event_filter=False, group_filter=True)
        seen: list[tuple] = []

        def capture(*_args, **_kwargs) -> list[str]:
            tags = get_query_tags()
            seen.append((tags.product, tags.scanner_id))
            return ["org-1"]

        with patch(
            "posthog.session_recordings.queries.sub_queries.group_key_resolver._query_group_keys",
            side_effect=capture,
        ):
            query.get_query()

        assert seen == [(Product.REPLAY_VISION, _SCANNER_ID)]

    def test_a_scanner_without_event_filters_has_nothing_to_correlate(self) -> None:
        predicates = session_in_predicates(self._query(filter_test_accounts=False, with_event_filter=False).get_query())

        assert predicates == []
