from __future__ import annotations

from typing import Any

from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.database.schema.error_tracking_fingerprint_issue_state import (
    _ISSUE_STATE_COLUMNS,
    RAW_TABLE_NAME,
    _build_union_with_pending_updates,
    _pending_update_select,
    select_from_error_tracking_fingerprint_issue_state_table,
)

VALID_ISSUE_ID = "01936e7f-d7ff-7314-b2d4-7627981e34f0"
VALID_ROLE_ID = "01936e80-5e69-7e70-b837-871f5cdad28b"


class TestPendingUpdateUnionBuilder(BaseTest):
    def _sanitized_row(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "fingerprint": "fp-1",
            "issue_id": VALID_ISSUE_ID,
            "issue_name": "MyError",
            "issue_description": "something broke",
            "issue_status": "active",
            "assigned_user_id": 42,
            "assigned_role_id": VALID_ROLE_ID,
            "first_seen": "2026-01-15 10:30:00.000000",
            "is_deleted": 0,
            "version": 1700000000,
        }
        base.update(overrides)
        return base

    def test_pending_update_select_columns_match_expected_order(self) -> None:
        select = _pending_update_select(self._sanitized_row())
        assert isinstance(select, ast.SelectQuery)
        aliases = [expr.alias for expr in select.select if isinstance(expr, ast.Alias)]
        self.assertEqual(aliases, _ISSUE_STATE_COLUMNS)

    def test_build_union_returns_base_plus_branches(self) -> None:
        pending_updates = [self._sanitized_row(fingerprint="fp-1"), self._sanitized_row(fingerprint="fp-2")]
        union = _build_union_with_pending_updates(pending_updates)
        assert isinstance(union, ast.SelectSetQuery)
        # 1 base + 2 pending-update branches = 3 total, expressed as initial + 2 subsequent
        self.assertEqual(len(union.subsequent_select_queries), 2)
        for node in union.subsequent_select_queries:
            self.assertEqual(node.set_operator, "UNION ALL")

    def test_base_branch_selects_columns_in_expected_order(self) -> None:
        union = _build_union_with_pending_updates([self._sanitized_row()])
        assert isinstance(union, ast.SelectSetQuery)
        base = union.initial_select_query
        assert isinstance(base, ast.SelectQuery)
        names = [f.chain[0] for f in base.select if isinstance(f, ast.Field)]
        self.assertEqual(names, _ISSUE_STATE_COLUMNS)
        assert isinstance(base.select_from, ast.JoinExpr)
        assert isinstance(base.select_from.table, ast.Field)
        self.assertEqual(base.select_from.table.chain, [RAW_TABLE_NAME])

    def test_select_without_pending_updates_scans_raw_table_directly(self) -> None:
        select = select_from_error_tracking_fingerprint_issue_state_table(
            requested_fields={"issue_id": ["issue_id"]},
        )
        assert isinstance(select.select_from, ast.JoinExpr)
        # No pending updates - the wrapper UNION isn't built; scan the raw table directly.
        assert isinstance(select.select_from.table, ast.Field)
        self.assertEqual(select.select_from.table.chain, [RAW_TABLE_NAME])

    def test_select_with_pending_updates_wraps_raw_table_with_union(self) -> None:
        select = select_from_error_tracking_fingerprint_issue_state_table(
            requested_fields={"issue_id": ["issue_id"]},
            pending_updates=[self._sanitized_row()],
        )
        assert isinstance(select.select_from, ast.JoinExpr)
        # With pending updates - the scan targets the UNION ALL wrapper aliased as the raw table.
        assert isinstance(select.select_from.table, ast.SelectSetQuery)
        self.assertEqual(select.select_from.alias, RAW_TABLE_NAME)
