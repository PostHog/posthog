from datetime import timedelta

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
        status: ObservationStatus = ObservationStatus.SUCCEEDED,
        created_at: timezone.datetime | None = None,
    ) -> ReplayObservation:
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
        assert impact.identified_users == 1

    def test_classifier_counts_every_succeeded_observation(self) -> None:
        scanner = self._make_scanner(ScannerType.CLASSIFIER)
        self._make_observation(scanner, session_id="s1", distinct_id="u1", verdict=None)
        self._make_observation(scanner, session_id="s2", distinct_id="u2", verdict=None)

        assert compute_scanner_impact(scanner).affected_sessions == 2

    def test_deduplicates_users_across_sessions(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")
        self._make_observation(scanner, session_id="s2", distinct_id="u1")

        impact = compute_scanner_impact(scanner)

        assert impact.affected_sessions == 2
        assert impact.identified_users == 1

    @parameterized.expand([("null", None), ("empty", "")])
    def test_splits_unidentified_sessions(self, _name: str, anonymous_value: str | None) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s-anon", distinct_id=anonymous_value)
        self._make_observation(scanner, session_id="s-known", distinct_id="u1")

        impact = compute_scanner_impact(scanner)

        assert impact.affected_sessions == 2
        assert impact.identified_users == 1
        assert impact.unidentified_sessions == 1

    def test_excludes_out_of_window_and_non_succeeded(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(
            scanner, session_id="s-old", distinct_id="u1", created_at=timezone.now() - timedelta(days=31)
        )
        self._make_observation(scanner, session_id="s-failed", distinct_id="u2", status=ObservationStatus.FAILED)
        self._make_observation(scanner, session_id="s-inel", distinct_id="u3", status=ObservationStatus.INELIGIBLE)

        assert compute_scanner_impact(scanner, window_days=30).affected_sessions == 0


class TestCreateAffectedCohort(_ImpactTestCase):
    def test_creates_static_cohort_with_deduped_distinct_ids(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")
        self._make_observation(scanner, session_id="s2", distinct_id="u1")
        self._make_observation(scanner, session_id="s3", distinct_id="u2")
        self._make_observation(scanner, session_id="s4", distinct_id=None)

        with patch.object(Cohort, "insert_users_by_list", return_value=1) as mock_insert:
            cohort, inserted = create_affected_cohort(scanner, self.user)

        assert inserted == 2
        assert sorted(mock_insert.call_args.args[0]) == ["u1", "u2"]
        cohort.refresh_from_db()
        assert cohort.is_static is True
        assert cohort.created_by == self.user
        assert scanner.name in cohort.name

    def test_raises_when_no_identified_users(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id=None)

        with pytest.raises(ValueError):
            create_affected_cohort(scanner, self.user)
        assert Cohort.objects.filter(team=self.team).count() == 0

    def test_deletes_cohort_when_insert_fails(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")

        with patch.object(Cohort, "insert_users_by_list", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
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
            "identified_users": 1,
            "unidentified_sessions": 0,
            "window_days": 30,
        }

    def test_affected_cohort_creates_and_returns_cohort(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)
        self._make_observation(scanner, session_id="s1", distinct_id="u1")

        with patch.object(Cohort, "insert_users_by_list", return_value=1):
            resp = self.client.post(
                f"/api/environments/{self.team.id}/vision/scanners/{scanner.id}/affected_cohort/",
                {"window_days": 7},
            )

        assert resp.status_code == 201, resp.json()
        body = resp.json()
        assert body["identified_users"] == 1
        assert body["window_days"] == 7
        assert Cohort.objects.filter(pk=body["cohort_id"], is_static=True).exists()

    def test_affected_cohort_400_when_no_identified_users(self) -> None:
        scanner = self._make_scanner(ScannerType.MONITOR)

        resp = self.client.post(
            f"/api/environments/{self.team.id}/vision/scanners/{scanner.id}/affected_cohort/",
            {},
        )

        assert resp.status_code == 400
