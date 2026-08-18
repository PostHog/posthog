import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.date_util import start_of_month
from posthog.models import Organization, Team

from products.replay_vision.backend import quota
from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import ReplayScannerPromptSuggestion
from products.replay_vision.backend.quota import (
    MONTHLY_CREDIT_QUOTA,
    BillingPeriod,
    ScannerBudget,
    _parse_org_credit_limit_overrides,
    compute_quota_snapshot,
    compute_scanner_budget,
    compute_scanner_budgets,
)
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for

_ORG_ID = "01234567-89ab-cdef-0123-456789abcdef"


class _VisionQuotaTestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="quota-test-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )

    def _make_observation(
        self,
        *,
        status: ObservationStatus,
        completed_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> ReplayObservation:
        observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=f"sess-{ReplayObservation.objects.count()}",
            status=status,
            scanner_snapshot=_snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            completed_at=completed_at,
        )
        if created_at is not None:
            ReplayObservation.objects.filter(pk=observation.pk).update(created_at=created_at)
            observation.refresh_from_db()
        if status == ObservationStatus.SUCCEEDED:
            # Mirror production: a succeeded observation has a usage receipt, which is what quota counts.
            self._make_receipt(observation)
        return observation

    @staticmethod
    def _make_receipt(observation: ReplayObservation) -> None:
        # Mirror production: the receipt freezes the snapshot model and its credit price.
        model = observation.scanner_snapshot.get("model", "")
        ReplayObservationUsage.objects.get_or_create(
            observation_id=observation.id,
            defaults={
                "organization_id": observation.team.organization_id,
                "team_id": observation.team_id,
                "scanner_id": observation.scanner_id,
                "observation_created_at": observation.created_at,
                "model": model,
                "credits": observation_credits_for_model(model),
            },
        )

    @staticmethod
    def _make_running_evaluation(
        *,
        scanner: ReplayScanner,
        total: int,
        status: str = "running",
        age: timedelta = timedelta(0),
        settled: int = 0,
    ) -> ReplayScannerPromptSuggestion:
        return ReplayScannerPromptSuggestion.objects.create(
            scanner=scanner,
            team=scanner.team,
            suggested_prompt="p",
            evaluation={
                "status": status,
                "started_at": (timezone.now() - age).isoformat(),
                "total": total,
                "results": [{"session_id": f"s-{i}"} for i in range(settled)],
            },
        )


class TestComputeQuotaSnapshot(_VisionQuotaTestCase):
    @parameterized.expand(
        [
            (ObservationStatus.SUCCEEDED, ScannerModel.GEMINI_3_5_FLASH_LITE, 2),
            (ObservationStatus.SUCCEEDED, ScannerModel.GEMINI_3_7_FLASH, 15),
            (ObservationStatus.PENDING, ScannerModel.GEMINI_3_5_FLASH_LITE, 2),
            (ObservationStatus.RUNNING, ScannerModel.GEMINI_3_7_FLASH, 15),
            (ObservationStatus.FAILED, ScannerModel.GEMINI_3_7_FLASH, 0),
            (ObservationStatus.INELIGIBLE, ScannerModel.GEMINI_3_7_FLASH, 0),
        ]
    )
    def test_credits_priced_by_model_for_succeeded_and_in_flight(
        self, status: ObservationStatus, model: ScannerModel, expected_credits: int
    ) -> None:
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(model=model)
        self.scanner.refresh_from_db()
        self._make_observation(
            status=status,
            completed_at=timezone.now()
            if status != ObservationStatus.PENDING and status != ObservationStatus.RUNNING
            else None,
        )
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == expected_credits

    def test_excludes_observations_created_in_a_previous_month(self) -> None:
        last_month = (datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)) - timedelta(days=1)
        self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=last_month, created_at=last_month)
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == 0

    def test_period_bounds_are_first_of_month_utc(self) -> None:
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.period_start.day == 1
        assert snapshot.period_start.tzinfo == UTC
        assert snapshot.period_end.day == 1
        assert snapshot.period_end > snapshot.period_start

    def test_december_rollover_advances_year(self) -> None:
        with patch("products.replay_vision.backend.quota.datetime", wraps=datetime) as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 12, 15, 10, tzinfo=UTC)
            snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.period_start == datetime(2026, 12, 1, tzinfo=UTC)
        assert snapshot.period_end == datetime(2027, 1, 1, tzinfo=UTC)

    def test_observations_at_period_boundaries(self) -> None:
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        self._make_observation(
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            created_at=snapshot.period_end - timedelta(microseconds=1),
        )
        self._make_observation(
            status=ObservationStatus.SUCCEEDED, completed_at=timezone.now(), created_at=snapshot.period_end
        )
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == 15

    def test_other_orgs_observations_not_counted(self) -> None:
        other_org = Organization.objects.create(name="other-org")
        other_team = Team.objects.create(organization=other_org, name="other-team")
        other_scanner = ReplayScanner.objects.create(
            team=other_team,
            name="other-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        other_obs = ReplayObservation.objects.create(
            scanner=other_scanner,
            team=other_team,
            session_id="other-sess",
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot=_snapshot_for(other_scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            completed_at=timezone.now(),
        )
        self._make_receipt(other_obs)
        self._make_running_evaluation(scanner=other_scanner, total=5)

        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.credits_used == 0

    @parameterized.expand(
        [
            ("running_counts_unsettled", "running", timedelta(0), 2, 3),
            # A dead workflow can't charge anymore, so a stale "running" row holds no quota.
            ("stale_running_ignored", "running", timedelta(hours=4), 0, 0),
            ("finished_ignored", "succeeded", timedelta(0), 0, 0),
        ]
    )
    def test_running_evaluations_count_unsettled_sessions(
        self, _name: str, status: str, age: timedelta, settled: int, expected_unsettled: int
    ) -> None:
        self._make_running_evaluation(scanner=self.scanner, total=5, status=status, age=age, settled=settled)
        expected = expected_unsettled * observation_credits_for_model(self.scanner.model)
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == expected

    def test_exhausted_when_usage_meets_quota(self) -> None:
        with patch("products.replay_vision.backend.quota.MONTHLY_CREDIT_QUOTA", 30):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())

            snapshot = compute_quota_snapshot(organization_id=self.organization.id)

            assert snapshot.credits_used == 30
            assert snapshot.exhausted is True
            assert snapshot.remaining == 0

    def test_deleting_scanner_does_not_refund_spent_usage(self) -> None:
        # Deleting a scanner cascade-deletes its observations, but the usage they spent must not be refunded.
        for _ in range(3):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == 45

        self.scanner.delete()

        assert ReplayObservation.objects.filter(team=self.team).count() == 0  # observations cascade-deleted
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == 45  # receipts survive

    def test_deleting_observation_does_not_refund_spent_usage(self) -> None:
        observation = self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == 15

        observation.delete()  # e.g. the admin recording-delete flow

        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == 15

    def test_no_double_count_across_pending_to_succeeded(self) -> None:
        observation = self._make_observation(status=ObservationStatus.PENDING)
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == 15  # reserved in-flight

        # The success transition flips status and writes the receipt, so the total stays 15.
        ReplayObservation.objects.filter(pk=observation.pk).update(
            status=ObservationStatus.SUCCEEDED, completed_at=timezone.now()
        )
        self._make_receipt(observation)
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == 15


class TestComputeScannerBudget(_VisionQuotaTestCase):
    def setUp(self) -> None:
        super().setUp()
        # Spend counting only runs for capped scanners; a wide-open limit keeps it from binding.
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=1_000_000)
        self.scanner.refresh_from_db()

    def _other_scanner(self) -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=self.team,
            name="other-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
            credit_limit=1_000_000,
        )

    def test_no_limit_set_is_uncapped(self) -> None:
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=None)
        self.scanner.refresh_from_db()
        budget = compute_scanner_budget(self.scanner)
        assert budget.credit_limit is None
        assert budget.remaining is None
        assert not budget.exhausted
        assert not budget.blocked
        assert not budget.would_exceed(10**9)

    def test_an_uncapped_scanner_skips_the_spend_aggregates(self) -> None:
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=None)
        self.scanner.refresh_from_db()
        self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        # Uncapped budgets report zero usage by design: nothing gates on them and the spend UI
        # only renders for capped scanners, so the aggregates are skipped entirely.
        budget = compute_scanner_budget(self.scanner)
        assert budget.credits_used == 0
        assert not budget.blocked

    @parameterized.expand(
        [
            (ObservationStatus.SUCCEEDED, 15),
            (ObservationStatus.PENDING, 15),
            (ObservationStatus.RUNNING, 15),
            (ObservationStatus.FAILED, 0),
            (ObservationStatus.INELIGIBLE, 0),
        ]
    )
    def test_counts_settled_receipts_and_in_flight_reservations(self, status: ObservationStatus, expected: int) -> None:
        is_in_flight = status in (ObservationStatus.PENDING, ObservationStatus.RUNNING)
        self._make_observation(status=status, completed_at=None if is_in_flight else timezone.now())
        assert compute_scanner_budget(self.scanner).credits_used == expected

    def test_another_scanners_spend_does_not_count(self) -> None:
        other = self._other_scanner()
        observation = ReplayObservation.objects.create(
            scanner=other,
            team=self.team,
            session_id="other-sess",
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot=_snapshot_for(other),
            triggered_by=ObservationTrigger.ON_DEMAND,
            completed_at=timezone.now(),
        )
        self._make_receipt(observation)
        assert compute_scanner_budget(self.scanner).credits_used == 0
        assert compute_scanner_budget(other).credits_used == 15

    def test_receipts_without_a_scanner_count_toward_nobody(self) -> None:
        observation = self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        ReplayObservationUsage.objects.filter(observation_id=observation.id).update(scanner_id=None)
        ReplayObservation.objects.filter(pk=observation.pk).delete()
        assert compute_scanner_budget(self.scanner).credits_used == 0

    def test_spend_in_a_previous_period_does_not_count(self) -> None:
        last_month = start_of_month(datetime.now(UTC)) - timedelta(days=1)
        self._make_observation(status=ObservationStatus.SUCCEEDED, created_at=last_month, completed_at=last_month)
        assert compute_scanner_budget(self.scanner).credits_used == 0

    def test_a_running_evaluation_reserves_against_the_scanners_own_cap(self) -> None:
        self._make_running_evaluation(scanner=self.scanner, total=4)
        assert compute_scanner_budget(self.scanner).credits_used == 4 * 15

    def test_another_scanners_running_evaluation_does_not_count(self) -> None:
        self._make_running_evaluation(scanner=self._other_scanner(), total=4)
        assert compute_scanner_budget(self.scanner).credits_used == 0

    def test_a_caller_supplied_period_is_billed_against(self) -> None:
        self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        previous = start_of_month(datetime.now(UTC)) - timedelta(days=1)
        period = BillingPeriod(start=start_of_month(previous), end=start_of_month(datetime.now(UTC)))
        assert compute_scanner_budget(self.scanner, period).credits_used == 0
        assert compute_scanner_budget(self.scanner).credits_used == 15

    def test_a_caller_supplied_period_scopes_in_flight_reservations_too(self) -> None:
        self._make_observation(status=ObservationStatus.RUNNING)
        previous = start_of_month(datetime.now(UTC)) - timedelta(days=1)
        period = BillingPeriod(start=start_of_month(previous), end=start_of_month(datetime.now(UTC)))
        assert compute_scanner_budget(self.scanner, period).credits_used == 0
        assert compute_scanner_budget(self.scanner).credits_used == 15

    def test_prices_one_more_observation_from_the_scanners_model(self) -> None:
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(model=ScannerModel.GEMINI_3_5_FLASH_LITE)
        self.scanner.refresh_from_db()
        assert compute_scanner_budget(self.scanner).credits_per_observation == 2

    def test_settled_credits_exclude_live_reservations(self) -> None:
        self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        self._make_observation(status=ObservationStatus.RUNNING)
        budget = compute_scanner_budget(self.scanner)
        assert budget.credits_used == 30
        assert budget.settled_credits == 15

    def test_an_observation_settling_between_the_budget_reads_never_vanishes(self) -> None:
        # Reservations are read before receipts, so a settlement between the reads is seen by both
        # (over-counted once, failing toward capped) instead of by neither (an admission past the cap).
        observation = self._make_observation(status=ObservationStatus.RUNNING)
        real_in_flight = quota._scanner_in_flight_credits

        def in_flight_then_settle(*args, **kwargs):
            reserved = real_in_flight(*args, **kwargs)
            ReplayObservation.objects.filter(pk=observation.pk).update(
                status=ObservationStatus.SUCCEEDED, completed_at=timezone.now()
            )
            observation.refresh_from_db()
            self._make_receipt(observation)
            return reserved

        with patch.object(quota, "_scanner_in_flight_credits", side_effect=in_flight_then_settle):
            budget = compute_scanner_budget(self.scanner)

        assert budget.credits_used >= 15


class TestBackfillUsageScannerId(_VisionQuotaTestCase):
    def test_backfills_null_scanner_ids_only_where_the_observation_still_exists(self) -> None:
        import uuid
        import importlib

        from django.apps import apps as django_apps
        from django.db import connection

        observation = self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        ReplayObservationUsage.objects.filter(observation_id=observation.id).update(scanner_id=None)
        orphan = ReplayObservationUsage.objects.create(
            organization_id=self.organization.id,
            observation_id=uuid.uuid4(),
            observation_created_at=timezone.now(),
        )

        migration = importlib.import_module("products.replay_vision.backend.migrations.0070_backfill_usage_scanner_id")
        with connection.schema_editor(atomic=False) as schema_editor:
            migration.backfill_scanner_id(django_apps, schema_editor)

        assert ReplayObservationUsage.objects.get(observation_id=observation.id).scanner_id == self.scanner.id
        orphan.refresh_from_db()
        assert orphan.scanner_id is None

    def test_backfill_attributes_all_receipts_across_batches(self) -> None:
        import uuid
        import importlib

        from django.apps import apps as django_apps
        from django.db import connection

        observations = [
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now()) for _ in range(3)
        ]
        ReplayObservationUsage.objects.filter(observation_id__in=[o.id for o in observations]).update(scanner_id=None)
        orphan = ReplayObservationUsage.objects.create(
            organization_id=self.organization.id,
            observation_id=uuid.uuid4(),
            observation_created_at=timezone.now(),
        )

        migration = importlib.import_module("products.replay_vision.backend.migrations.0070_backfill_usage_scanner_id")
        # BATCH_SIZE=1 forces one keyset iteration per receipt, exercising the pagination loop.
        with patch.object(migration, "BATCH_SIZE", 1):
            with connection.schema_editor(atomic=False) as schema_editor:
                migration.backfill_scanner_id(django_apps, schema_editor)

        for observation in observations:
            assert ReplayObservationUsage.objects.get(observation_id=observation.id).scanner_id == self.scanner.id
        orphan.refresh_from_db()
        assert orphan.scanner_id is None


class TestRebackfillUsageScannerId(_VisionQuotaTestCase):
    def test_rebackfill_attributes_receipts_across_batches_and_leaves_orphans_null(self) -> None:
        import uuid
        import importlib

        from django.apps import apps as django_apps
        from django.db import connection

        observations = [
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now()) for _ in range(3)
        ]
        ReplayObservationUsage.objects.filter(observation_id__in=[o.id for o in observations]).update(scanner_id=None)
        orphan = ReplayObservationUsage.objects.create(
            organization_id=self.organization.id,
            observation_id=uuid.uuid4(),
            observation_created_at=timezone.now(),
        )

        migration = importlib.import_module(
            "products.replay_vision.backend.migrations.0073_rebackfill_usage_scanner_id"
        )
        # BATCH_SIZE=1 forces one keyset iteration per receipt, exercising the pagination loop.
        with patch.object(migration, "BATCH_SIZE", 1):
            with connection.schema_editor(atomic=False) as schema_editor:
                migration.rebackfill_scanner_id(django_apps, schema_editor)

        for observation in observations:
            assert ReplayObservationUsage.objects.get(observation_id=observation.id).scanner_id == self.scanner.id
        orphan.refresh_from_db()
        assert orphan.scanner_id is None


class TestScannerBudgetBlocked(SimpleTestCase):
    @parameterized.expand(
        [
            ("uncapped", None, 10_000, False, False, None),
            ("fresh_budget", 100, 0, False, False, 100),
            ("room_for_one_more", 100, 85, False, False, 15),
            # The gap `exhausted` misses: under one observation of headroom left, so the next
            # observation cannot be admitted even though usage has not reached the limit.
            ("less_than_one_observation_left", 100, 90, False, True, 10),
            ("exactly_at_the_limit", 100, 100, True, True, 0),
            ("overshot", 100, 130, True, True, 0),
        ]
    )
    def test_blocked_is_the_one_answer_for_out_of_budget(
        self,
        _name: str,
        credit_limit: int | None,
        credits_used: int,
        expected_exhausted: bool,
        expected_blocked: bool,
        expected_remaining: int | None,
    ) -> None:
        budget = ScannerBudget(
            credit_limit=credit_limit,
            credits_used=credits_used,
            period_start=datetime(2026, 8, 1, tzinfo=UTC),
            period_end=datetime(2026, 9, 1, tzinfo=UTC),
            credits_per_observation=15,
            settled_credits=credits_used,
        )
        assert budget.exhausted == expected_exhausted
        assert budget.blocked == expected_blocked
        assert budget.remaining == expected_remaining

    @parameterized.expand(
        [
            # A free model spends nothing, so it scans through and past the limit without blocking.
            ("at_the_limit_still_admits", 100, True, False),
            ("over_the_limit_blocks", 101, True, True),
        ]
    )
    def test_zero_cost_observations_block_only_when_strictly_over(
        self, _name: str, credits_used: int, expected_exhausted: bool, expected_blocked: bool
    ) -> None:
        budget = ScannerBudget(
            credit_limit=100,
            credits_used=credits_used,
            period_start=datetime(2026, 8, 1, tzinfo=UTC),
            period_end=datetime(2026, 9, 1, tzinfo=UTC),
            credits_per_observation=0,
            settled_credits=credits_used,
        )
        assert budget.exhausted == expected_exhausted
        assert budget.blocked == expected_blocked

    @parameterized.expand(
        [
            ("reservations_alone_cap_it", 30, 100, True, False),
            ("settled_spend_alone_caps_it", 95, 95, True, True),
            ("neither_caps_it", 30, 50, False, False),
        ]
    )
    def test_blocked_by_settled_spend_ignores_live_reservations(
        self,
        _name: str,
        settled_credits: int,
        credits_used: int,
        expected_blocked: bool,
        expected_blocked_by_settled: bool,
    ) -> None:
        budget = ScannerBudget(
            credit_limit=100,
            credits_used=credits_used,
            period_start=datetime(2026, 8, 1, tzinfo=UTC),
            period_end=datetime(2026, 9, 1, tzinfo=UTC),
            credits_per_observation=15,
            settled_credits=settled_credits,
        )
        assert budget.blocked == expected_blocked
        assert budget.blocked_by_settled_spend == expected_blocked_by_settled


class TestComputeScannerBudgets(_VisionQuotaTestCase):
    def setUp(self) -> None:
        super().setUp()
        # Spend counting only runs for capped scanners; a wide-open limit keeps it from binding.
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=1_000_000)
        self.scanner.refresh_from_db()

    def test_returns_an_entry_for_every_requested_scanner_including_unspent(self) -> None:
        unspent = ReplayScanner.objects.create(
            team=self.team,
            name="unspent-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        result = compute_scanner_budgets(self.organization.id, [self.scanner.id, unspent.id])
        assert result[self.scanner.id].credits_used == 15
        assert result[unspent.id].credits_used == 0

    def test_reads_each_scanners_own_limit(self) -> None:
        capped = ReplayScanner.objects.create(
            team=self.team,
            name="capped-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
            credit_limit=300,
        )
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=None)
        result = compute_scanner_budgets(self.organization.id, [self.scanner.id, capped.id])
        assert result[self.scanner.id].credit_limit is None
        assert result[capped.id].credit_limit == 300

    def test_another_orgs_scanner_id_contributes_nothing(self) -> None:
        other_org = Organization.objects.create(name="other-budgets-org")
        other_team = Team.objects.create(organization=other_org, name="other-budgets-team")
        other_scanner = ReplayScanner.objects.create(
            team=other_team,
            name="other-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        ReplayScanner.objects.filter(pk=other_scanner.pk).update(credit_limit=1000)
        # One of each spend source, so dropping the org filter from any single query fails this.
        settled = ReplayObservation.objects.create(
            scanner=other_scanner,
            team=other_team,
            session_id="other-settled",
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot=_snapshot_for(other_scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            completed_at=timezone.now(),
        )
        self._make_receipt(settled)
        ReplayObservation.objects.create(
            scanner=other_scanner,
            team=other_team,
            session_id="other-sess",
            status=ObservationStatus.RUNNING,
            scanner_snapshot=_snapshot_for(other_scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
        )
        self._make_running_evaluation(scanner=other_scanner, total=4)
        result = compute_scanner_budgets(self.organization.id, [other_scanner.id])
        assert result[other_scanner.id].credits_used == 0
        assert result[other_scanner.id].credit_limit is None


class TestBillingSyncedQuota(_VisionQuotaTestCase):
    @parameterized.expand(
        [
            ("billing_limit_wins", {"replay_vision_credits": {"limit": 42, "usage": 0}}, 42),
            (
                "synced_without_limit_is_uncapped",
                {"replay_vision_credits": {"limit": None, "usage": 0}},
                None,
            ),
            ("float_limit_honored", {"replay_vision_credits": {"limit": 42.0, "usage": 0}}, 42),
            (
                "malformed_limit_falls_back_not_uncapped",
                {"replay_vision_credits": {"limit": "42", "usage": 0}},
                MONTHLY_CREDIT_QUOTA,
            ),
            # Billing writes `{}` for products it doesn't manage yet; that's unsynced, not uncapped.
            ("empty_summary_falls_back", {"replay_vision_credits": {}}, MONTHLY_CREDIT_QUOTA),
            ("key_missing_falls_back", {"events": {"limit": 100, "usage": 0}}, MONTHLY_CREDIT_QUOTA),
            ("usage_empty_falls_back", None, MONTHLY_CREDIT_QUOTA),
        ]
    )
    def test_credit_limit_source(self, _name: str, usage: dict | None, expected_quota: int | None) -> None:
        self.organization.usage = usage
        self.organization.save()
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.credit_limit == expected_quota

    @parameterized.expand(
        [
            # An unlimited plan (billing syncs no limit) gets the override as its cap.
            ("caps_an_uncapped_org", {"replay_vision_credits": {"limit": None, "usage": 0}}, 500, 500),
            ("tighter_override_wins", {"replay_vision_credits": {"limit": 42, "usage": 0}}, 10, 10),
            # The override can only reduce credits; a looser value never overrides billing.
            ("looser_override_ignored", {"replay_vision_credits": {"limit": 42, "usage": 0}}, 9000, 42),
        ]
    )
    def test_org_credit_limit_override(self, _name: str, usage: dict, override: int, expected_quota: int) -> None:
        self.organization.usage = usage
        self.organization.save()
        with patch.dict(
            "products.replay_vision.backend.quota.ORG_CREDIT_LIMIT_OVERRIDES",
            {str(self.organization.id): override},
        ):
            snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.credit_limit == expected_quota

    def test_override_for_another_org_changes_nothing(self) -> None:
        self.organization.usage = {"replay_vision_credits": {"limit": None, "usage": 0}}
        self.organization.save()
        with patch.dict(
            "products.replay_vision.backend.quota.ORG_CREDIT_LIMIT_OVERRIDES",
            {str(uuid.uuid4()): 500},
        ):
            snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.credit_limit is None

    @parameterized.expand(
        [
            ("canonical_id", '{"01234567-89ab-cdef-0123-456789abcdef": 500000}', {_ORG_ID: 500000}),
            # Written another way, the same org must still be capped rather than silently uncapped.
            ("uppercase_id", '{"01234567-89AB-CDEF-0123-456789ABCDEF": 500000}', {_ORG_ID: 500000}),
            ("unhyphenated_id", '{"0123456789abcdef0123456789abcdef": 500000}', {_ORG_ID: 500000}),
            # A negative cap would read as already over, so a typo blocks the org rather than freeing it.
            ("negative_value_clamped", '{"01234567-89ab-cdef-0123-456789abcdef": -5}', {_ORG_ID: 0}),
            ("not_an_object", "[1, 2]", {}),
            ("non_int_value", '{"01234567-89ab-cdef-0123-456789abcdef": "lots"}', {}),
            ("non_uuid_key", '{"not-an-org": 500000}', {}),
            # int(True) is 1, which would cap the org at a single credit rather than not at all.
            ("boolean_value", '{"01234567-89ab-cdef-0123-456789abcdef": true}', {}),
            ("invalid_json", "{nope", {}),
        ]
    )
    def test_parse_org_credit_limit_overrides(self, _name: str, raw: str, expected: dict) -> None:
        assert _parse_org_credit_limit_overrides(raw) == expected

    def test_one_bad_entry_does_not_void_the_others(self) -> None:
        raw = '{"not-an-org": 1, "01234567-89ab-cdef-0123-456789abcdef": 500000}'
        assert _parse_org_credit_limit_overrides(raw) == {_ORG_ID: 500000}

    def test_uncapped_org_is_never_exhausted(self) -> None:
        self.organization.usage = {"replay_vision_credits": {"limit": None, "usage": 0}}
        self.organization.save()
        self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())

        snapshot = compute_quota_snapshot(organization_id=self.organization.id)

        assert snapshot.credit_limit is None
        assert snapshot.remaining is None
        assert not snapshot.exhausted

    def test_billing_period_bounds_used_when_current(self) -> None:
        now = datetime.now(UTC)
        start = now - timedelta(days=10)
        end = now + timedelta(days=20)
        self.organization.usage = {"period": [start.isoformat(), end.isoformat()]}
        self.organization.save()
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.period_start == start
        assert snapshot.period_end == end
        # Usage is counted against the billing window, not the calendar month.
        self._make_observation(
            status=ObservationStatus.SUCCEEDED, completed_at=timezone.now(), created_at=start - timedelta(days=1)
        )
        assert compute_quota_snapshot(organization_id=self.organization.id).credits_used == 0

    def test_naive_billing_period_does_not_crash(self) -> None:
        now = datetime.now(UTC)
        start = now - timedelta(days=5)
        end = now + timedelta(days=25)
        # A period stored without a tz offset must not raise when compared against tz-aware now.
        self.organization.usage = {
            "period": [start.replace(tzinfo=None).isoformat(), end.replace(tzinfo=None).isoformat()]
        }
        self.organization.save()
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.period_start == start
        assert snapshot.period_end == end

    def test_stale_billing_period_falls_back_to_calendar_month(self) -> None:
        now = datetime.now(UTC)
        self.organization.usage = {
            "period": [(now - timedelta(days=70)).isoformat(), (now - timedelta(days=40)).isoformat()]
        }
        self.organization.save()
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.period_start == start_of_month(now)
        assert snapshot.period_end > now


class TestProjectedMonthlyObservations(_VisionQuotaTestCase):
    def _make_scanner(
        self,
        *,
        team: Team,
        name: str,
        enabled: bool = True,
        estimate: int | None = None,
        model: ScannerModel = ScannerModel.GEMINI_3_7_FLASH,
    ) -> None:
        scanner = ReplayScanner.objects.create(
            team=team,
            name=name,
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=model,
            enabled=enabled,
        )
        if estimate is not None:
            ReplayScanner.objects.filter(pk=scanner.pk).update(
                estimated_monthly_observations=estimate, estimated_at=timezone.now()
            )

    def test_sums_credit_weighted_estimates_across_org_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="second-team")
        self._make_scanner(team=self.team, name="a", estimate=100)  # 100 × 5 credits
        self._make_scanner(team=other_team, name="b", estimate=250, model=ScannerModel.GEMINI_3_5_FLASH_LITE)  # 250 × 2
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.projected_monthly_credits == 100 * 15 + 250 * 2

    def test_disabled_and_unestimated_scanners_contribute_zero(self) -> None:
        self._make_scanner(team=self.team, name="disabled", enabled=False, estimate=500)
        self._make_scanner(team=self.team, name="unestimated", estimate=None)
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.projected_monthly_credits == 0

    def test_other_orgs_scanners_not_counted(self) -> None:
        other_org = Organization.objects.create(name="other-projection-org")
        other_team = Team.objects.create(organization=other_org, name="other-projection-team")
        self._make_scanner(team=other_team, name="other", estimate=999)
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.projected_monthly_credits == 0


class TestVisionQuotaEndpoint(_VisionQuotaTestCase):
    @property
    def quota_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/quota/"

    def test_returns_static_quota_and_zero_usage_when_empty(self) -> None:
        resp = self.client.get(self.quota_url)
        assert resp.status_code == 200, resp.json()
        body = resp.json()
        assert body["credit_limit"] == MONTHLY_CREDIT_QUOTA
        assert body["credits_used"] == 0
        assert body["remaining"] == MONTHLY_CREDIT_QUOTA
        assert body["exhausted"] is False
        assert body["projected_monthly_credits"] == 0
        assert body["free_monthly_credits"] == 2500
        assert "period_start" in body
        assert "period_end" in body

    def test_returns_fleet_projection(self) -> None:
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(
            estimated_monthly_observations=120, estimated_at=timezone.now()
        )
        resp = self.client.get(self.quota_url)
        assert resp.json()["projected_monthly_credits"] == 120 * 15

    def test_reflects_recent_succeeded_observations(self) -> None:
        for _ in range(3):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())

        resp = self.client.get(self.quota_url)
        assert resp.json()["credits_used"] == 45
        assert resp.json()["remaining"] == MONTHLY_CREDIT_QUOTA - 45


@patch("products.replay_vision.backend.api.trigger.async_to_sync")
@patch("products.replay_vision.backend.api.trigger.sync_connect")
class TestObserveQuotaEnforcement(_VisionQuotaTestCase):
    @property
    def observe_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/scanners/{self.scanner.id}/observe/"

    def test_returns_402_when_quota_exhausted(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        with patch("products.replay_vision.backend.quota.MONTHLY_CREDIT_QUOTA", 5):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())

            resp = self.client.post(self.observe_url, data={"session_id": "sess-blocked"}, format="json")

            assert resp.status_code == 402, resp.json()
            body = resp.json()
            assert body["code"] == "quota_limit_exceeded"
            assert "would exceed your monthly Replay vision limit of $0.05" in body["detail"]
            mock_sync_connect.assert_not_called()
            mock_async_to_sync.assert_not_called()

    def test_returns_402_when_observation_would_exceed_remaining(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Not exhausted (15 of 25 used), but the next 15-credit observation would land at 30 > 25. The precheck
        # must reject it rather than only blocking once fully exhausted.
        with patch("products.replay_vision.backend.quota.MONTHLY_CREDIT_QUOTA", 25):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
            assert not compute_quota_snapshot(organization_id=self.organization.id).exhausted

            resp = self.client.post(self.observe_url, data={"session_id": "sess-would-exceed"}, format="json")

            assert resp.status_code == 402, resp.json()
            mock_sync_connect.assert_not_called()

    def test_allows_observe_when_under_quota(self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()

        resp = self.client.post(self.observe_url, data={"session_id": "sess-ok"}, format="json")
        assert resp.status_code == 202, resp.json()
        # Only the workflow start hits Temporal now; the team capacity check counts DB rows.
        mock_sync_connect.assert_called_once()

    def test_returns_429_when_team_at_in_flight_cap(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        with patch("products.replay_vision.backend.api.trigger.MAX_IN_FLIGHT_APPLIES_PER_TEAM", 1):
            self._make_observation(status=ObservationStatus.RUNNING)

            resp = self.client.post(self.observe_url, data={"session_id": "sess-capped"}, format="json")

            assert resp.status_code == 429, resp.json()
            assert "observations running" in resp.json()["detail"]
            # Blocked before any workflow start.
            mock_sync_connect.assert_not_called()


class TestBillingPeriodValidation(SimpleTestCase):
    START = datetime(2026, 7, 1, tzinfo=UTC)

    def test_accepts_ordered_bounds(self) -> None:
        period = BillingPeriod(start=self.START, end=self.START + timedelta(days=31))
        assert period.end - period.start == timedelta(days=31)

    @parameterized.expand([("empty", timedelta(0)), ("reversed", timedelta(seconds=-1))])
    def test_rejects_empty_or_reversed_window(self, _name: str, delta: timedelta) -> None:
        with self.assertRaisesRegex(ValueError, "start"):
            BillingPeriod(start=self.START, end=self.START + delta)
