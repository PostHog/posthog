from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from products.replay_vision.backend.cluster_lifecycle import ClusterStatus, cluster_status

NOW = datetime(2026, 10, 29, tzinfo=UTC)


@parameterized.expand(
    [
        ("new", 3, 0, 4, 0, "", None, ClusterStatus.EMERGING),
        ("steady", 30, 0, 10, 9, "", None, ClusterStatus.ACTIVE),
        ("halving", 30, 1, 3, 10, "", None, ClusterStatus.FADING),
        ("quiet", 60, 20, 0, 0, "", None, ClusterStatus.DORMANT),
        ("known_and_growing", 30, 0, 10, 2, "known", 5, ClusterStatus.KNOWN),
        ("resolved_and_quiet", 30, 6, 0, 3, "resolved", 5, ClusterStatus.RESOLVED),
        ("resolved_then_new_members", 30, 1, 2, 3, "resolved", 5, ClusterStatus.REGRESSED),
        ("not_an_issue", 30, 0, 10, 2, "not_an_issue", 5, ClusterStatus.NOT_AN_ISSUE),
    ]
)
def test_cluster_status(
    _name: str,
    age_days: int,
    quiet_days: int,
    last_week: int,
    week_before: int,
    review: str,
    reviewed_days_ago: int | None,
    expected: ClusterStatus,
) -> None:
    status = cluster_status(
        now=NOW,
        first_member_at=NOW - timedelta(days=age_days),
        last_member_at=NOW - timedelta(days=quiet_days),
        last_week=last_week,
        week_before=week_before,
        review_state=review,
        reviewed_at=NOW - timedelta(days=reviewed_days_ago) if reviewed_days_ago is not None else None,
    )

    assert status == expected
