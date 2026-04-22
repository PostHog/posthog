from __future__ import annotations

import datetime
from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import DateRange, ErrorTrackingPhantomFingerprintIssueState, ErrorTrackingQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.error_tracking_fingerprint_issue_state import (
    _PHANTOM_COLUMNS,
    RAW_TABLE_NAME,
    _build_union_with_phantoms,
    _phantom_select,
    _phantoms_from_context,
)

from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import (
    MAX_FINGERPRINT_PHANTOMS,
    ErrorTrackingQueryRunner,
    _coerce_first_seen,
)

VALID_ISSUE_ID = "01936e7f-d7ff-7314-b2d4-7627981e34f0"
VALID_ROLE_ID = "01936e80-5e69-7e70-b837-871f5cdad28b"


def _build_phantom(**overrides: Any) -> ErrorTrackingPhantomFingerprintIssueState:
    defaults: dict[str, Any] = {
        "fingerprint": "fp-1",
        "issue_id": VALID_ISSUE_ID,
        "issue_name": "MyError",
        "issue_description": "something broke",
        "issue_status": "active",
        "assigned_user_id": 42,
        "assigned_role_id": VALID_ROLE_ID,
        "first_seen": "2026-01-15T10:30:00Z",
        "is_deleted": 0,
        "version": 1700000000,
    }
    defaults.update(overrides)
    return ErrorTrackingPhantomFingerprintIssueState(**defaults)


class TestCoerceFirstSeen(BaseTest):
    @parameterized.expand(
        [
            ("z_suffix", "2026-01-15T10:30:00Z", "2026-01-15 10:30:00.000000"),
            ("offset_utc", "2026-01-15T10:30:00+00:00", "2026-01-15 10:30:00.000000"),
            ("offset_nonutc", "2026-01-15T12:30:00+02:00", "2026-01-15 10:30:00.000000"),
            ("naive", "2026-01-15T10:30:00", "2026-01-15 10:30:00.000000"),
            ("microseconds", "2026-01-15T10:30:00.123456Z", "2026-01-15 10:30:00.123456"),
        ]
    )
    def test_valid_formats(self, _name: str, value: str, expected: str) -> None:
        self.assertEqual(_coerce_first_seen(value), expected)

    def test_accepts_datetime_object(self) -> None:
        dt = datetime.datetime(2026, 1, 15, 10, 30, 0, tzinfo=datetime.UTC)
        self.assertEqual(_coerce_first_seen(dt), "2026-01-15 10:30:00.000000")

    def test_rejects_invalid_string(self) -> None:
        with self.assertRaises(ValidationError):
            _coerce_first_seen("not-a-date")


class TestSanitizeFingerprintPhantoms(BaseTest):
    def _runner(self, phantoms: list[ErrorTrackingPhantomFingerprintIssueState] | None) -> ErrorTrackingQueryRunner:
        return ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
                orderBy="last_seen",
                volumeResolution=1,
                phantomFingerprintIssueStates=phantoms,
            ),
        )

    def test_empty_when_none(self) -> None:
        runner = self._runner(None)
        self.assertEqual(runner._sanitized_fingerprint_phantoms, [])

    def test_empty_when_empty_list(self) -> None:
        runner = self._runner([])
        self.assertEqual(runner._sanitized_fingerprint_phantoms, [])

    def test_happy_path_stamps_team_id(self) -> None:
        runner = self._runner([_build_phantom()])
        [row] = runner._sanitized_fingerprint_phantoms
        self.assertEqual(row["team_id"], self.team.id)
        self.assertEqual(row["fingerprint"], "fp-1")
        self.assertEqual(row["issue_id"], VALID_ISSUE_ID)
        self.assertEqual(row["issue_status"], "active")
        self.assertEqual(row["assigned_user_id"], 42)
        self.assertEqual(row["assigned_role_id"], VALID_ROLE_ID)
        self.assertEqual(row["is_deleted"], 0)
        self.assertEqual(row["version"], 1700000000)
        # first_seen is normalized for CH
        self.assertEqual(row["first_seen"], "2026-01-15 10:30:00.000000")

    @parameterized.expand(
        [
            ("invalid_issue_id", {"issue_id": "not-a-uuid"}),
            ("invalid_status", {"issue_status": "not-a-real-status"}),
            ("invalid_role_id", {"assigned_role_id": "not-a-uuid"}),
            ("invalid_first_seen", {"first_seen": "not-a-date"}),
        ]
    )
    def test_rejects_invalid_field(self, _name: str, override: dict[str, Any]) -> None:
        runner = self._runner([_build_phantom(**override)])
        with self.assertRaises(ValidationError):
            _ = runner._sanitized_fingerprint_phantoms

    def test_rejects_too_many_rows(self) -> None:
        rows = [_build_phantom(fingerprint=f"fp-{i}") for i in range(MAX_FINGERPRINT_PHANTOMS + 1)]
        runner = self._runner(rows)
        with self.assertRaises(ValidationError):
            _ = runner._sanitized_fingerprint_phantoms

    def test_accepts_max_rows(self) -> None:
        rows = [_build_phantom(fingerprint=f"fp-{i}") for i in range(MAX_FINGERPRINT_PHANTOMS)]
        runner = self._runner(rows)
        sanitized = runner._sanitized_fingerprint_phantoms
        self.assertEqual(len(sanitized), MAX_FINGERPRINT_PHANTOMS)

    def test_nullable_fields_pass_through_none(self) -> None:
        phantom = _build_phantom(
            issue_name=None,
            issue_description=None,
            assigned_user_id=None,
            assigned_role_id=None,
        )
        runner = self._runner([phantom])
        [row] = runner._sanitized_fingerprint_phantoms
        self.assertIsNone(row["issue_name"])
        self.assertIsNone(row["issue_description"])
        self.assertIsNone(row["assigned_user_id"])
        self.assertIsNone(row["assigned_role_id"])


class TestPhantomUnionBuilder(BaseTest):
    def _sanitized_row(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "team_id": self.team.id,
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

    def test_phantom_select_columns_match_expected_order(self) -> None:
        select = _phantom_select(self._sanitized_row())
        assert isinstance(select, ast.SelectQuery)
        aliases = [expr.alias for expr in select.select if isinstance(expr, ast.Alias)]
        self.assertEqual(aliases, _PHANTOM_COLUMNS)

    def test_build_union_returns_base_plus_branches(self) -> None:
        phantoms = [self._sanitized_row(fingerprint="fp-1"), self._sanitized_row(fingerprint="fp-2")]
        union = _build_union_with_phantoms(phantoms)
        assert isinstance(union, ast.SelectSetQuery)
        # 1 base + 2 phantom branches = 3 total, expressed as initial + 2 subsequent
        self.assertEqual(len(union.subsequent_select_queries), 2)
        for node in union.subsequent_select_queries:
            self.assertEqual(node.set_operator, "UNION ALL")

    def test_base_branch_selects_columns_in_expected_order(self) -> None:
        union = _build_union_with_phantoms([self._sanitized_row()])
        assert isinstance(union, ast.SelectSetQuery)
        base = union.initial_select_query
        assert isinstance(base, ast.SelectQuery)
        names = [f.chain[0] for f in base.select if isinstance(f, ast.Field)]
        self.assertEqual(names, _PHANTOM_COLUMNS)
        assert isinstance(base.select_from, ast.JoinExpr)
        assert isinstance(base.select_from.table, ast.Field)
        self.assertEqual(base.select_from.table.chain, [RAW_TABLE_NAME])

    def test_phantoms_from_context_missing_or_empty(self) -> None:
        self.assertEqual(_phantoms_from_context(None), [])
        self.assertEqual(_phantoms_from_context(HogQLContext(team_id=self.team.id)), [])

    def test_phantoms_from_context_returns_rows(self) -> None:
        ctx = HogQLContext(team_id=self.team.id)
        rows = [self._sanitized_row()]
        ctx.error_tracking_fingerprint_phantoms = rows
        self.assertEqual(_phantoms_from_context(ctx), rows)
