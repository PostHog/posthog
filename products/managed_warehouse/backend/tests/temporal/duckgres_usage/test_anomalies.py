"""Tests for the anomaly table — the withhold/proceed policy matrix, as a pure unit.

The activity-level tests in test_poll_activity.py pin each anomaly end to end
(persist + capture + ack decision against a real database). These pin the matrix
itself: that each condition is detected, carries the right policy bit, and maps
to the right exception class — fast, no database.
"""

import datetime as dt

import pytest

from products.managed_warehouse.backend.temporal.duckgres_usage.anomalies import detect_anomalies, regression_anomaly
from products.managed_warehouse.backend.temporal.duckgres_usage.client import UsageResponse
from products.managed_warehouse.backend.temporal.duckgres_usage.team_resolution import ResolvedTeams

LOW = dt.datetime(2026, 7, 5, 23, 59, 59, tzinfo=dt.UTC)
HIGH = dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC)


def _response(**kwargs) -> UsageResponse:
    return UsageResponse(watermark_low=LOW, watermark_high=HIGH, rows=[], **kwargs)


def _resolution(**kwargs) -> ResolvedTeams:
    return ResolvedTeams(compute_rows=[], storage_rows=[], orphaned_org_ids=set(), **kwargs)


def test_clean_pull_detects_nothing() -> None:
    assert detect_anomalies(_response(), _resolution(), recorded=None, out_of_window=0) == []


# The full matrix: every anomaly kind, the condition that raises it, and its policy
# bit. recoverable=True → the caller withholds the ack; False → the ack proceeds.
MATRIX = [
    # (kind, recoverable, exception class name, response kwargs, resolution kwargs, recorded, out_of_window)
    ("watermark_hole", True, "DuckgresWatermarkHole", {}, {}, LOW - dt.timedelta(days=1), 0),
    ("parse_failure", True, "DuckgresRowParseError", {"unparsed_row_count": 1}, {}, None, 0),
    ("out_of_window", True, "DuckgresRowsOutsideWindow", {}, {}, None, 2),
    ("orphaned_org", False, "DuckgresUsageOrphanedOrg", {}, {"orphaned_org_ids": {"018f-x"}}, None, 0),
    ("malformed_org", False, "DuckgresMalformedOrgRows", {}, {"malformed_org_row_count": 1}, None, 0),
    ("foreign_team", False, "DuckgresForeignTeamRows", {}, {"foreign_team_row_count": 1}, None, 0),
    ("duplicate_rows", False, "DuckgresDuplicateRows", {}, {"duplicate_row_count": 1}, None, 0),
    (
        "conflicting_rows",
        True,
        "DuckgresConflictingRows",
        {},
        {"conflicting_row_count": 1, "conflicting_org_ids": {"018f-conflict"}},
        None,
        0,
    ),
    ("invalid_value", False, "DuckgresInvalidValueRows", {"invalid_value_row_count": 1}, {}, None, 0),
    ("usage_missing", True, "DuckgresMissingUsage", {"usage_missing": True}, {}, None, 0),
    ("storage_malformed", True, "DuckgresMalformedStorage", {"storage_malformed": True}, {}, None, 0),
]


@pytest.mark.parametrize(
    "kind,recoverable,exception_name,response_kwargs,resolution_kwargs,recorded,out_of_window",
    MATRIX,
    ids=[row[0] for row in MATRIX],
)
def test_each_kind_is_detected_with_its_policy(
    kind, recoverable, exception_name, response_kwargs, resolution_kwargs, recorded, out_of_window
) -> None:
    # A resolution kwarg like orphaned_org_ids overrides the default empty one.
    resolution = ResolvedTeams(
        compute_rows=[],
        storage_rows=[],
        orphaned_org_ids=resolution_kwargs.pop("orphaned_org_ids", set()),
        **resolution_kwargs,
    )
    found = detect_anomalies(_response(**response_kwargs), resolution, recorded=recorded, out_of_window=out_of_window)

    assert [a.kind for a in found] == [kind]
    anomaly = found[0]
    assert anomaly.recoverable is recoverable
    assert type(anomaly.to_exception()).__name__ == exception_name
    assert anomaly.message  # every alert carries a human-readable detail
    if kind == "conflicting_rows":
        assert anomaly.organization_ids == frozenset({"018f-conflict"})
    elif recoverable:
        assert anomaly.organization_ids is None


def test_multiple_anomalies_are_all_detected() -> None:
    found = detect_anomalies(
        _response(unparsed_row_count=1, invalid_value_row_count=1),
        _resolution(duplicate_row_count=1),
        recorded=None,
        out_of_window=0,
    )
    assert {a.kind for a in found} == {"parse_failure", "invalid_value", "duplicate_rows"}


def test_no_hole_when_nothing_was_ever_recorded() -> None:
    # First-ever pull: no recorded watermark can't read as a hole, whatever the low.
    assert detect_anomalies(_response(), _resolution(), recorded=None, out_of_window=0) == []


def test_behind_is_not_a_hole() -> None:
    # Our record AHEAD of duckgres (a prior ack didn't stick) is the benign
    # direction — logged by the activity, never an anomaly.
    ahead = LOW + dt.timedelta(days=2)
    assert detect_anomalies(_response(), _resolution(), recorded=ahead, out_of_window=0) == []


def test_regression_anomaly_is_scoped_and_recoverable() -> None:
    anomaly = regression_anomaly({"org-a", "org-b"})

    assert anomaly.kind == "usage_regression"
    assert anomaly.recoverable is True
    assert anomaly.organization_ids == frozenset({"org-a", "org-b"})
