from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from products.experiments.backend.facade.contracts import ConcludedExperiment, FlagCleanupPlan
from products.feature_flags.backend.facade.api import FlagSummary
from products.reaperhog.backend.logic.enrollment import FlagEnrollment
from products.reaperhog.backend.logic.repo import CommitStamp, ReferenceCount
from products.reaperhog.backend.logic.scouts.archaeology import classify_directory
from products.reaperhog.backend.logic.scouts.experiments import classify_experiment
from products.reaperhog.backend.logic.scouts.flags import classify_flag

NOW = datetime(2026, 8, 30, tzinfo=UTC)
REFERENCE = ReferenceCount(files=("a.py", "b.tsx", "test_a.py"), total=4)


def _days_ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


def _summary(**overrides: object) -> FlagSummary:
    values: dict[str, object] = {
        "id": 1,
        "key": "k",
        "active": True,
        "deleted": False,
        "archived": False,
        "created_at": _days_ago(400),
        "updated_at": _days_ago(400),
        "last_called_at": _days_ago(1),
        "status": "active",
        "status_reason": "",
        "effectively_full_rollout": False,
        "max_rollout_percentage": 50,
        "has_enrollment_overrides": False,
        "variant_keys": (),
        "fully_rolled_out_variant": None,
    }
    values.update(overrides)
    return FlagSummary(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "summary,decisive,fragment",
    [
        (None, True, "No flag row"),
        (_summary(deleted=True), True, "deleted"),
        (_summary(archived=True), True, "archived"),
        (_summary(active=False, updated_at=_days_ago(91)), False, "disabled for at least 91 days"),
        (_summary(max_rollout_percentage=0, updated_at=_days_ago(90)), False, "0% rollout for at least 90 days"),
        (_summary(last_called_at=_days_ago(366)), False, "not evaluated in 366 days"),
        (_summary(last_called_at=None, created_at=_days_ago(366)), False, "never evaluated"),
        (
            _summary(effectively_full_rollout=True, fully_rolled_out_variant="test", created_at=_days_ago(181)),
            False,
            'keep variant "test"',
        ),
        (_summary(effectively_full_rollout=True, created_at=_days_ago(181)), False, "keep the enabled path"),
    ],
)
def test_classify_flag_hits(summary: FlagSummary | None, decisive: bool, fragment: str) -> None:
    hit = classify_flag("k", summary, REFERENCE, NOW)

    assert hit is not None
    assert hit.decisive is decisive
    assert fragment in hit.summary
    assert hit.files == ["a.py", "b.tsx", "test_a.py"]
    assert hit.evidence["code_files"] == 2
    assert hit.evidence["test_files"] == 1
    assert hit.evidence["users"] == 0


@pytest.mark.parametrize(
    "summary",
    [
        _summary(),
        _summary(active=False, updated_at=_days_ago(89)),
        _summary(max_rollout_percentage=0, updated_at=_days_ago(89)),
        _summary(max_rollout_percentage=0, updated_at=_days_ago(90), has_enrollment_overrides=True),
        _summary(last_called_at=_days_ago(364)),
        _summary(last_called_at=None, created_at=_days_ago(364)),
        _summary(effectively_full_rollout=True, created_at=_days_ago(179)),
    ],
)
def test_classify_flag_leaves_live_flags_alone(summary: FlagSummary) -> None:
    assert classify_flag("k", summary, REFERENCE, NOW) is None


def _enrollment(users: int, enabled_users: int) -> FlagEnrollment:
    return FlagEnrollment(
        evaluations=users * 3, users=users, enabled_evaluations=enabled_users * 3, enabled_users=enabled_users
    )


@pytest.mark.parametrize(
    "summary,enrollment,dead",
    [
        (_summary(), _enrollment(500, 0), True),
        (_summary(max_rollout_percentage=0, has_enrollment_overrides=True), _enrollment(500, 0), True),
        (_summary(), _enrollment(499, 0), False),
        (_summary(), _enrollment(500, 1), False),
        (_summary(effectively_full_rollout=True, created_at=_days_ago(100)), _enrollment(500, 0), False),
        (_summary(), None, False),
    ],
)
def test_classify_flag_reads_observed_enrollment(
    summary: FlagSummary, enrollment: FlagEnrollment | None, dead: bool
) -> None:
    hit = classify_flag("k", summary, REFERENCE, NOW, enrollment)

    if not dead:
        assert hit is None
        return
    assert hit is not None
    assert hit.decisive is False
    assert "checked by 500 users in 90 days and enabled for none" in hit.summary
    assert hit.evidence["users"] == 500
    assert hit.evidence["enabled_users"] == 0


def _experiment(conclusion: str, plan: FlagCleanupPlan) -> ConcludedExperiment:
    return ConcludedExperiment(
        id=7,
        name="Hero copy",
        feature_flag_id=3,
        feature_flag_key="hero-copy",
        conclusion=conclusion,
        end_date=_days_ago(30),
        archived=False,
        flag_cleanup_task_id=uuid4(),
        variant_keys=("control", "test"),
        cleanup=plan,
    )


@pytest.mark.parametrize(
    "conclusion,plan,decisive,fragment",
    [
        ("won", FlagCleanupPlan("test", ("control",), "shipped", True), True, 'keep "test", remove "control"'),
        ("lost", FlagCleanupPlan("control", ("test",), "rollback", True), True, 'keep "control", remove "test"'),
        ("inconclusive", FlagCleanupPlan("control", ("test",), "confirm", False), False, "inconclusive"),
        ("won", FlagCleanupPlan(None, ("control", "test"), "ambiguous", False), False, "decide the kept path"),
    ],
)
def test_classify_experiment(conclusion: str, plan: FlagCleanupPlan, decisive: bool, fragment: str) -> None:
    hit = classify_experiment(_experiment(conclusion, plan), REFERENCE, _enrollment(500, 500))

    assert hit.root == "hero-copy"
    assert hit.decisive is decisive
    assert fragment in hit.summary
    assert hit.evidence["conclusion"] == conclusion
    assert hit.evidence["enabled_users"] == 500


def _stamp(days: int, subject: str = "Add thing") -> CommitStamp:
    return CommitStamp(sha="abc", committed_at=_days_ago(days), author_email="a@example.com", subject=subject)


@pytest.mark.parametrize(
    "stamp,author_left,fragment",
    [
        (_stamp(541), False, "no real commit in 541 days"),
        (_stamp(181), True, "no longer in the org"),
        (_stamp(91, "Hackathon: add thing"), False, "hackathon or spike"),
        (_stamp(541, "wip spike"), True, "no real commit in 541 days; last committer"),
    ],
)
def test_classify_directory_hits(stamp: CommitStamp, author_left: bool, fragment: str) -> None:
    hit = classify_directory("products/old", stamp, NOW, author_left)

    assert hit is not None
    assert fragment in hit.summary.lower()
    assert hit.files == ["products/old"]


@pytest.mark.parametrize(
    "stamp,author_left",
    [
        (_stamp(539), False),
        (_stamp(179), True),
        (_stamp(89, "Hackathon: add thing"), False),
        (_stamp(400), None),
    ],
)
def test_classify_directory_leaves_active_directories_alone(stamp: CommitStamp, author_left: bool | None) -> None:
    assert classify_directory("products/old", stamp, NOW, author_left) is None
