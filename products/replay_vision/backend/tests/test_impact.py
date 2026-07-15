from datetime import datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.cohorts.backend.models.cohort import Cohort
from products.replay_vision.backend.impact import compute_scanner_impact, create_affected_cohort
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for


class _ImpactTestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()

    def tearDown(self) -> None:
        self.flag_patcher.stop()
        super().tearDown()

    def _make_scanner(self, scanner_type: ScannerType = ScannerType.MONITOR) -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=self.team,
            name=f"impact-{scanner_type}-{ReplayScanner.objects.count()}",
            scanner_type=scanner_type,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
        )

    def _make_observation(
        self,
        scanner: ReplayScanner,
        *,
        session_id: str,
        distinct_id: str | None,
        verdict: str | None = "yes",
        result: dict | None = None,
        status: ObservationStatus = ObservationStatus.SUCCEEDED,
        created_at: datetime | None = None,
        session_started_at: datetime | None = None,
    ) -> ReplayObservation:
        if result is None:
            result = {"model_output": {"verdict": verdict}} if verdict is not None else {}
        observation = ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=session_id,
            distinct_id=distinct_id,
            status=status,
            scanner_snapshot=_snapshot_for(scanner),
            scanner_result=result,
            triggered_by=ObservationTrigger.SCHEDULE,
            session_started_at=session_started_at,
            # DB constraint: terminal statuses carry completed_at.
            completed_at=timezone.now() if status != ObservationStatus.PENDING else None,
        )
        if created_at is not None:
            ReplayObservation.objects.filter(pk=observation.pk).update(created_at=created_at)
        return observation


class TestComputeScannerImpact(_ImpactTestCase):
    def test_monitor_counts_only_verdict_yes(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s-yes", distinct_id="u1", verdict="yes")
        self._make_observation(scanner, session_id="s-no", distinct_id="u2", verdict="no")
        self._make_observation(scanner, session_id="s-inc", distinct_id="u3", verdict="inconclusive")

        impact = compute_scanner_impact(scanner)

        assert impact.affected_sessions == 1
        assert impact.affected_users == 1

    def test_classifier_counts_only_sessions_with_the_tag(self) -> None:
        scanner = self._make_scanner(ScannerType.CLASSIFIER)
        self._make_observation(scanner, session_id="s1", distinct_id="u1", result={"model_output": {"tags": ["bug"]}})
        self._make_observation(
            scanner, session_id="s2", distinct_id="u2", result={"model_output": {"tags_freeform": ["bug"]}}
        )
        self._make_observation(scanner, session_id="s3", distinct_id="u3", result={"model_output": {"tags": ["ux"]}})

        assert compute_scanner_impact(scanner, tag="bug").affected_sessions == 2

    def test_scorer_counts_only_sessions_within_score_bounds(self) -> None:
        scanner = self._make_scanner(ScannerType.SCORER)
        self._make_observation(scanner, session_id="s1", distinct_id="u1", result={"model_output": {"score": 8}})
        self._make_observation(scanner, session_id="s2", distinct_id="u2", result={"model_output": {"score": 3}})
        self._make_observation(
            scanner, session_id="s3", distinct_id="u3", result={"model_output": {"score": "corrupt"}}
        )

        assert compute_scanner_impact(scanner, min_score=7).affected_sessions == 1
        assert compute_scanner_impact(scanner, max_score=5).affected_sessions == 1

    @parameterized.expand(
        [
            ("monitor_rejects_tag", ScannerType.MONITOR, {"tag": "bug"}),
            ("classifier_requires_tag", ScannerType.CLASSIFIER, {}),
            ("scorer_requires_bound", ScannerType.SCORER, {}),
            ("summarizer_unsupported", ScannerType.SUMMARIZER, {}),
        ]
    )
    def test_rejects_invalid_qualifiers_per_type(self, _name: str, scanner_type: ScannerType, kwargs: dict) -> None:
        scanner = self._make_scanner(scanner_type)
        with pytest.raises(ValueError):
            compute_scanner_impact(scanner, **kwargs)

    def test_deduplicates_users_across_sessions(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")
        self._make_observation(scanner, session_id="s2", distinct_id="u1")

        impact = compute_scanner_impact(scanner)

        assert impact.affected_sessions == 2
        assert impact.affected_users == 1

    @parameterized.expand([("null", None), ("empty", "")])
    def test_splits_sessions_without_user(self, _name: str, anonymous_value: str | None) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s-anon", distinct_id=anonymous_value)
        self._make_observation(scanner, session_id="s-known", distinct_id="u1")

        impact = compute_scanner_impact(scanner)

        assert impact.affected_sessions == 2
        assert impact.affected_users == 1
        assert impact.sessions_without_user == 1

    def test_excludes_out_of_window_backfills_and_non_succeeded(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(
            scanner, session_id="s-old", distinct_id="u1", created_at=timezone.now() - timedelta(days=31)
        )
        # Backfill: old session scanned today must not count as current impact.
        self._make_observation(
            scanner, session_id="s-backfill", distinct_id="u2", session_started_at=timezone.now() - timedelta(days=45)
        )
        self._make_observation(scanner, session_id="s-failed", distinct_id="u3", status=ObservationStatus.FAILED)
        self._make_observation(scanner, session_id="s-inel", distinct_id="u4", status=ObservationStatus.INELIGIBLE)

        assert compute_scanner_impact(scanner, window_days=30).affected_sessions == 0


def _fake_insert(members: int):
    def insert(self: Cohort, items: list[str], **kwargs: Any) -> int:
        Cohort.objects.filter(pk=self.pk).update(count=members)
        return 1

    return insert


class TestCreateAffectedCohort(_ImpactTestCase):
    def test_creates_static_cohort_and_reports_real_member_count(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")
        self._make_observation(scanner, session_id="s2", distinct_id="u1")
        self._make_observation(scanner, session_id="s3", distinct_id="u2")
        self._make_observation(scanner, session_id="s4", distinct_id=None)

        # One of the two distinct ids resolves to no person; the reported count must be the cohort's, not the input's.
        with patch.object(Cohort, "insert_users_by_list", autospec=True, side_effect=_fake_insert(1)) as mock_insert:
            cohort, inserted = create_affected_cohort(scanner, self.user)

        assert inserted == 1
        assert sorted(mock_insert.call_args.args[1]) == ["u1", "u2"]
        assert mock_insert.call_args.kwargs["raise_on_error"] is True
        cohort.refresh_from_db()
        assert cohort.is_static is True
        assert cohort.created_by == self.user
        assert scanner.name in (cohort.name or "")

    def test_raises_when_no_users_in_window(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id=None)

        with pytest.raises(ValueError):
            create_affected_cohort(scanner, self.user)
        assert Cohort.objects.filter(team=self.team).count() == 0

    def test_raises_when_over_size_cap(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")
        self._make_observation(scanner, session_id="s2", distinct_id="u2")

        with patch("products.replay_vision.backend.impact.MAX_COHORT_DISTINCT_IDS", 1):
            with pytest.raises(ValueError):
                create_affected_cohort(scanner, self.user)
        assert Cohort.objects.filter(team=self.team).count() == 0

    @parameterized.expand(
        [
            ("insert_raises", "raise", RuntimeError),
            ("no_persons_resolved", "empty", ValueError),
        ]
    )
    def test_failed_or_empty_population_leaves_no_cohort(
        self, _name: str, mode: str, expected: type[Exception]
    ) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")

        side_effect = RuntimeError("boom") if mode == "raise" else _fake_insert(0)
        with patch.object(Cohort, "insert_users_by_list", autospec=True, side_effect=side_effect):
            with pytest.raises(expected):
                create_affected_cohort(scanner, self.user)
        assert Cohort.objects.filter(team=self.team).count() == 0


class TestImpactEndpoints(_ImpactTestCase):
    def test_impact_returns_counts(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")

        resp = self.client.get(f"/api/environments/{self.team.id}/vision/scanners/{scanner.id}/impact/")

        assert resp.status_code == 200, resp.json()
        assert resp.json() == {
            "affected_sessions": 1,
            "affected_users": 1,
            "sessions_without_user": 0,
            "window_days": 30,
        }

    def test_affected_cohort_creates_and_returns_cohort(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")

        with patch.object(Cohort, "insert_users_by_list", autospec=True, side_effect=_fake_insert(1)):
            resp = self.client.post(
                f"/api/environments/{self.team.id}/vision/scanners/{scanner.id}/affected_cohort/",
                {"window_days": 7},
            )

        assert resp.status_code == 201, resp.json()
        body = resp.json()
        assert body["users_in_cohort"] == 1
        assert body["window_days"] == 7
        assert Cohort.objects.filter(pk=body["cohort_id"], is_static=True).exists()

    def test_affected_cohort_400_when_no_users(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)

        resp = self.client.post(
            f"/api/environments/{self.team.id}/vision/scanners/{scanner.id}/affected_cohort/",
            {},
        )

        assert resp.status_code == 400

    def test_impact_400_when_qualifier_invalid_for_type(self) -> None:
        scanner = self._make_scanner(ScannerType.SUMMARIZER)

        resp = self.client.get(f"/api/environments/{self.team.id}/vision/scanners/{scanner.id}/impact/")

        assert resp.status_code == 400

    def test_impact_passes_qualifiers_through(self) -> None:
        scanner = self._make_scanner(ScannerType.CLASSIFIER)
        self._make_observation(scanner, session_id="s1", distinct_id="u1", result={"model_output": {"tags": ["bug"]}})
        self._make_observation(scanner, session_id="s2", distinct_id="u2", result={"model_output": {"tags": ["ux"]}})

        resp = self.client.get(
            f"/api/environments/{self.team.id}/vision/scanners/{scanner.id}/impact/",
            {"tag": "bug", "window_days": "7"},
        )

        assert resp.status_code == 200, resp.json()
        assert resp.json()["affected_sessions"] == 1
        assert resp.json()["window_days"] == 7
