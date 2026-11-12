from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import connection

import jwt
from parameterized import parameterized

from posthog.models import Organization, Team

from products.signals.backend.models import SignalSpend
from products.signals.backend.rated_usage_models import SignalRatedUsage
from products.signals.backend.rated_usage_tasks import (
    enqueue_signals_rated_usage,
    report_signals_rated_usage,
    report_signals_trial_grant,
)
from products.signals.backend.spend_billing import get_signals_spend_billing_credits_by_team
from products.signals.backend.test.test_billing import _at
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.rated_usage import trial_pool_id

from ee.models.license import License


@time_machine.travel(_at(12), tick=False)
class TestSignalsRatedUsage(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.usage = {"signals_spend_credits": {"billing_start_date": "2026-06-10"}}
        self.organization.save(update_fields=["usage"])
        self.license = License(key="synthetic-license::synthetic-secret", plan="enterprise")
        self.license_cache = patch("posthog.cloud_utils.instance_license_cached", self.license)
        self.license_cache.start()
        self.addCleanup(self.license_cache.stop)

    def _spend(
        self,
        amount: str,
        *,
        team: Team | None = None,
        day: int = 10,
        exempt: bool = False,
        usage_billing: bool = True,
        grant: SignalTrialGrant | None = None,
    ) -> None:
        with time_machine.travel(_at(day), tick=False):
            SignalSpend.objects.for_team((team or self.team).id).create(
                team=team or self.team,
                signal_id=uuid4(),
                kind=SignalSpend.Kind.AD_HOC,
                spend=Decimal(amount),
                finalized_at=_at(day),
                billing_exempt=exempt or grant is not None,
                usage_billing=usage_billing,
                trial_grant=grant,
            )

    def _grant(self, *, allowance_microusd: int = 10_000_000) -> SignalTrialGrant:
        with time_machine.travel(_at(9), tick=False):
            return SignalTrialGrant.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                organization_id=self.organization.id,
                claimed_by_id=self.user.id,
                allowance_microusd=allowance_microusd,
            )

    @staticmethod
    def _accepted_response(url: str, **kwargs: object) -> MagicMock:
        if url.endswith("external-credit-pools"):
            return MagicMock(status_code=200, json=lambda: {"result": "created"})
        return MagicMock(status_code=200, json=lambda: {"results": ["created"]})

    @parameterized.expand(
        [(10_000_000, 1000, "created"), (20_000_000, 2000, "created"), (10_000_000, 1000, "replayed")]
    )
    @patch("ee.billing.billing_manager.http_session.post")
    def test_claimed_allowance_is_reported_before_any_usage(
        self, allowance: int, cents: int, result: str, post: MagicMock
    ) -> None:
        grant = self._grant(allowance_microusd=allowance)
        post.return_value = MagicMock(status_code=200, json=lambda: {"result": result})
        report_signals_trial_grant.run(grant.team_id, str(grant.id))
        report_signals_trial_grant.run(grant.team_id, str(grant.id))
        grant.refresh_from_db()
        assert grant.billing_reported_at == _at(12)
        assert grant.billing_pool_allocated_cents == 0
        assert not SignalRatedUsage.objects.for_team(self.team.id).exists()
        assert post.call_count == 1
        assert post.call_args.args[0].endswith("/api/rated-usage/external-credit-pools")
        assert post.call_args.kwargs["json"] == {"grant_id": trial_pool_id(grant), "cents": cents, "day": "2026-06-09"}

    @parameterized.expand([(404, {}), (401, {}), (500, {}), (200, {"result": "conflict"}), (200, {}), (200, [])])
    @patch("ee.billing.billing_manager.http_session.post")
    def test_failed_pool_is_not_acknowledged(self, status: int, body: object, post: MagicMock) -> None:
        grant = self._grant()
        post.return_value = MagicMock(status_code=status, json=lambda: body, ok=status == 200)
        with pytest.raises(Exception):
            report_signals_trial_grant.run(grant.team_id, str(grant.id))
        grant.refresh_from_db()
        assert grant.billing_reported_at is None

    @patch("ee.billing.billing_manager.http_session.post")
    def test_grant_reporting_cannot_issue_another_projects_pool(self, post: MagicMock) -> None:
        grant = self._grant()
        other_team = Team.objects.create(organization=self.organization, name="Another project")

        report_signals_trial_grant.run(other_team.id, str(grant.id))

        post.assert_not_called()
        grant.refresh_from_db()
        assert grant.billing_reported_at is None

    @parameterized.expand(
        [("0.49", "10.51", 11, 0), ("0.51", "10.49", 11, 1), ("0.3", "0.3", 1, 0), ("19", "1200", 1219, 19)]
    )
    @patch("ee.billing.billing_manager.http_session.post")
    def test_trial_allocation_keeps_the_paid_meter_and_absorbs_spillover(
        self, paid: str, trial: str, total_cents: int, owed_cents: int, post: MagicMock
    ) -> None:
        grant = self._grant()
        self._spend(paid)
        self._spend(trial, grant=grant, usage_billing=False)
        self._spend("200", exempt=True)
        self._spend("300", usage_billing=False)
        savepoints = list(connection.savepoint_ids)

        def accepted(url: str, **kwargs: object) -> MagicMock:
            assert connection.savepoint_ids == savepoints
            return self._accepted_response(url, **kwargs)

        post.side_effect = accepted
        report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        payload = post.call_args.kwargs["json"]["items"][0]
        assert payload["cents"] == total_cents
        shares = payload["grants"]
        assert sum(share["cents"] for share in shares) == total_cents - owed_cents
        paid_meter = dict(get_signals_spend_billing_credits_by_team(_at(10, 0), _at(11, 0), self.organization.id))
        assert paid_meter.get(self.team.id, 0) == owed_cents
        pool_calls = post.call_args_list[:-1]
        assert all(call.args[0].endswith("external-credit-pools") for call in pool_calls)
        assert pool_calls[0].kwargs["json"] == {"grant_id": trial_pool_id(grant), "cents": 1000, "day": "2026-06-09"}
        grant.refresh_from_db()
        assert grant.billing_pool_allocated_cents == min(total_cents - owed_cents, 1000)
        if total_cents - owed_cents > 1000:
            assert pool_calls[1].kwargs["json"]["cents"] == 200
            assert pool_calls[1].kwargs["json"]["day"] == "2026-06-10"
        assert SignalRatedUsage.objects.for_team(self.team.id).get().reported_at == _at(12)

    @parameterized.expand([("timeout",), ("conflict",), ("http_error",)])
    @patch("ee.billing.billing_manager.http_session.post")
    def test_pool_failure_prevents_usage_delivery_and_retries_the_frozen_allocation(
        self, failure: str, post: MagicMock
    ) -> None:
        grant = self._grant()
        self._spend("600", grant=grant)
        if failure == "timeout":
            post.side_effect = TimeoutError("lost pool acknowledgement")
        else:
            post.return_value = MagicMock(
                status_code=200 if failure == "conflict" else 500,
                json=lambda: {"result": "conflict"},
            )
        with pytest.raises(Exception):
            report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        post.assert_called_once()
        assert post.call_args.args[0].endswith("external-credit-pools")
        delivery = SignalRatedUsage.objects.for_team(self.team.id).get()
        frozen = delivery.grants
        assert delivery.reported_at is None
        post.reset_mock()
        post.side_effect = self._accepted_response
        report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        delivery.refresh_from_db()
        grant.refresh_from_db()
        assert delivery.grants == frozen
        assert delivery.reported_at == _at(12)
        assert grant.billing_pool_allocated_cents == 600
        assert post.call_count == 2

    @patch("ee.billing.billing_manager.http_session.post")
    def test_lost_acknowledgement_reuses_allocations_after_other_days_consume_the_pool(self, post: MagicMock) -> None:
        grant = self._grant()
        self._spend("600", grant=grant)
        post.side_effect = [self._accepted_response("external-credit-pools"), TimeoutError("lost acknowledgement")]
        with pytest.raises(TimeoutError):
            report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        original_payload = post.call_args.kwargs["json"]
        original = SignalRatedUsage.objects.for_team(self.team.id).get()
        assert original.reported_at is None
        self._spend("600", grant=grant, day=11)
        post.side_effect = self._accepted_response
        report_signals_rated_usage.run(str(self.organization.id), "2026-06-11")
        grant.refresh_from_db()
        assert grant.billing_pool_allocated_cents == 1000
        report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        assert post.call_args.kwargs["json"] == original_payload
        grant.refresh_from_db()
        original.refresh_from_db()
        assert grant.billing_pool_allocated_cents == 1000
        assert original.reported_at == _at(12)

    @patch("ee.billing.billing_manager.http_session.post")
    def test_transferred_trial_remains_free_without_drawing_on_the_old_customers_pool(self, post: MagicMock) -> None:
        grant = self._grant()
        post.side_effect = self._accepted_response
        report_signals_trial_grant.run(grant.team_id, str(grant.id))
        original_pool = post.call_args.kwargs["json"]
        other_org = Organization.objects.create(name="Transferred project customer")
        self.team.organization = other_org
        self.team.save(update_fields=["organization"])
        self._spend("600", grant=grant)
        post.reset_mock()
        report_signals_rated_usage.run(str(other_org.id), "2026-06-10")
        pool = post.call_args_list[0].kwargs["json"]
        item = post.call_args_list[1].kwargs["json"]["items"][0]
        assert pool["grant_id"] != original_pool["grant_id"]
        assert pool["cents"] == 600
        assert item["cents"] == 600
        assert item["grants"] == [{"grant_id": pool["grant_id"], "cents": 600}]
        grant.refresh_from_db()
        assert grant.organization_id == self.organization.id
        assert grant.billing_pool_allocated_cents == 0
        for call in post.call_args_list:
            token = call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
            claims = jwt.decode(token, "synthetic-secret", algorithms=["HS256"], audience="posthog:license-key")
            assert claims["organization_id"] == str(other_org.id)

    def test_daily_sweep_repairs_grant_issuance_and_reports_trial_usage_before_usage_json_sync(self) -> None:
        grant = self._grant()
        self._spend("600", grant=grant, usage_billing=False)
        with (
            patch("products.signals.backend.rated_usage_tasks.report_signals_trial_grant.delay") as pools,
            patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as usage,
        ):
            enqueue_signals_rated_usage.run()
        pools.assert_called_once_with(grant.team_id, str(grant.id))
        usage.assert_called_once_with(str(self.organization.id), "2026-06-10")

    @patch("ee.billing.billing_manager.http_session.post")
    def test_direct_report_matches_meter_and_skips_acknowledged_delivery(self, post: MagicMock) -> None:
        self._spend("1.49")
        self._spend("1.49")
        self._spend("50", exempt=True)
        self._spend("60", day=9)
        self._spend("70", day=11)
        other_org = Organization.objects.create(name="Another organization", usage=self.organization.usage)
        other_team = Team.objects.create(organization=other_org)
        self._spend("80", team=other_team)
        post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"results": ["created"]}),
            MagicMock(status_code=200, json=lambda: {"results": ["replayed"]}),
        ]

        report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        assert SignalRatedUsage.objects.for_team(self.team.id).get().reported_at == _at(12)

        expected = {"items": [{"team_id": self.team.id, "product": "inbox_usage", "day": "2026-06-10", "cents": 3}]}
        assert dict(get_signals_spend_billing_credits_by_team(_at(10, 0), _at(11, 0), self.organization.id)) == {
            self.team.id: 3
        }
        assert post.call_count == 1
        for call in post.call_args_list:
            assert call.args[0].endswith("/api/rated-usage")
            assert call.kwargs["json"] == expected
            assert call.kwargs["timeout"] == 30
            token = call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
            claims = jwt.decode(token, "synthetic-secret", algorithms=["HS256"], audience="posthog:license-key")
            assert claims["organization_id"] == str(self.organization.id)
            assert claims["service_action"] == "rated_usage"
            assert "distinct_id" not in claims

    @parameterized.expand([("complete", False), ("second_batch_fails", True)])
    @patch("ee.billing.billing_manager.http_session.post")
    def test_report_respects_the_endpoint_batch_limit(
        self, _name: str, second_batch_fails: bool, post: MagicMock
    ) -> None:
        teams = Team.objects.bulk_create(
            [Team(organization=self.organization, project=self.team.project) for _ in range(1001)]
        )
        SignalSpend.objects.unscoped().bulk_create(
            [
                SignalSpend(
                    team=team,
                    signal_id=uuid4(),
                    kind=SignalSpend.Kind.AD_HOC,
                    spend=1,
                    finalized_at=_at(10),
                    usage_billing=True,
                )
                for team in teams
            ]
        )
        post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"results": ["created"] * 1000}),
            TimeoutError("synthetic failure of the second batch")
            if second_batch_fails
            else MagicMock(status_code=200, json=lambda: {"results": ["created"]}),
        ]
        with pytest.raises(TimeoutError) if second_batch_fails else nullcontext():
            report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        assert [len(call.kwargs["json"]["items"]) for call in post.call_args_list] == [1000, 1]
        assert {item["team_id"] for call in post.call_args_list for item in call.kwargs["json"]["items"]} == {
            team.id for team in teams
        }
        assert (
            SignalRatedUsage.objects.unscoped()
            .filter(organization_id=self.organization.id, reported_at__isnull=False)
            .count()
        ) == (1000 if second_batch_fails else 1001)

        post.reset_mock()
        post.side_effect = None
        post.return_value = MagicMock(status_code=200, json=lambda: {"results": ["created"]})
        report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        assert [len(call.kwargs["json"]["items"]) for call in post.call_args_list] == (
            [1] if second_batch_fails else []
        )
        assert (
            not SignalRatedUsage.objects.unscoped()
            .filter(organization_id=self.organization.id, reported_at__isnull=True)
            .exists()
        )

    @parameterized.expand(
        [
            ("missing_endpoint", 404, {}),
            ("unauthorized", 401, {}),
            ("server_error", 500, {}),
            ("conflict", 200, {"results": ["conflict"]}),
            ("missing_results", 200, {}),
            ("incomplete_results", 200, {"results": []}),
        ]
    )
    def test_failed_or_conflicting_delivery_raises(self, _name: str, status: int, body: dict) -> None:
        self._spend("3")
        response = MagicMock(status_code=status, json=lambda: body, ok=status == 200)
        with patch("ee.billing.billing_manager.http_session.post", return_value=response), pytest.raises(Exception):
            report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        assert SignalRatedUsage.objects.for_team(self.team.id).get().reported_at is None

    @patch("ee.billing.billing_manager.http_session.post")
    def test_sweep_retries_unacknowledged_usage_after_seven_days(self, post: MagicMock) -> None:
        self._spend("250")
        post.side_effect = TimeoutError("synthetic timeout after acceptance")
        with pytest.raises(TimeoutError):
            report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        original_payload = post.call_args.kwargs["json"]

        with time_machine.travel(_at(20), tick=False):
            with patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as enqueue:
                enqueue_signals_rated_usage.run()
            enqueue.assert_called_once_with(str(self.organization.id), "2026-06-10")

            post.side_effect = None
            post.return_value = MagicMock(status_code=200, json=lambda: {"results": ["replayed"]})
            report_signals_rated_usage.run(*enqueue.call_args.args)
            assert post.call_args.kwargs["json"] == original_payload
            assert SignalRatedUsage.objects.for_team(self.team.id).get().reported_at == _at(20)

            with patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as enqueue:
                enqueue_signals_rated_usage.run()
            enqueue.assert_not_called()

    @parameterized.expand([("today", "2026-06-12"), ("future", "2026-06-13")])
    def test_open_days_are_rejected(self, _name: str, day: str) -> None:
        with patch("ee.billing.billing_manager.http_session.post") as post, pytest.raises(ValueError):
            report_signals_rated_usage.run(str(self.organization.id), day)
        post.assert_not_called()

    def test_sweep_enqueues_only_recent_closed_days_with_metered_usage(self) -> None:
        self._spend("1")
        self._spend("2")
        self._spend("3", day=11)
        self._spend("4", day=12)
        self._spend("5", day=4)
        self._spend("6", day=8, exempt=True)
        self._spend("7", day=9, usage_billing=False)
        with patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as enqueue:
            enqueue_signals_rated_usage.run()
        assert [call.args for call in enqueue.call_args_list] == [
            (str(self.organization.id), "2026-06-10"),
            (str(self.organization.id), "2026-06-11"),
        ]
        with patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as enqueue:
            enqueue_signals_rated_usage.run(day=date(2026, 6, 10).isoformat())
        enqueue.assert_called_once_with(str(self.organization.id), "2026-06-10")

    @parameterized.expand([(True,), (False,)])
    def test_sweep_preserves_the_work_meter_after_a_plan_change(self, usage_billing: bool) -> None:
        self._spend("25", usage_billing=usage_billing)
        self.organization.usage = {"signals_spend_credits": {"usage": 0, "limit": 0}}
        self.organization.save(update_fields=["usage"])
        with patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as enqueue:
            enqueue_signals_rated_usage.run()
        assert [call.args for call in enqueue.call_args_list] == (
            [(str(self.organization.id), "2026-06-10")] if usage_billing else []
        )

    @parameterized.expand([("successful_delivery", False), ("lost_acknowledgment", True)])
    @patch("ee.billing.billing_manager.http_session.post")
    def test_project_move_does_not_change_the_customer_on_replay(
        self, _name: str, lost_acknowledgment: bool, post: MagicMock
    ) -> None:
        self._spend("250")
        post.return_value = MagicMock(status_code=200, json=lambda: {"results": ["replayed"]})
        if lost_acknowledgment:
            post.side_effect = TimeoutError("synthetic timeout after acceptance")
            with pytest.raises(TimeoutError):
                report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
            post.side_effect = None
        else:
            report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        original_payload = post.call_args.kwargs["json"]
        other_org = Organization.objects.create(name="Destination", usage=self.organization.usage)
        Team.objects.filter(id=self.team.id).update(organization=other_org)
        post.reset_mock()
        with patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as enqueue:
            enqueue_signals_rated_usage.run(day="2026-06-10")
        assert {call.args[0] for call in enqueue.call_args_list} == {str(self.organization.id), str(other_org.id)}
        for call in enqueue.call_args_list:
            report_signals_rated_usage.run(*call.args)
        if not lost_acknowledgment:
            post.assert_not_called()
            return
        post.assert_called_once()
        assert post.call_args.kwargs["json"] == original_payload
        token = post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(token, "synthetic-secret", algorithms=["HS256"], audience="posthog:license-key")
        assert claims["organization_id"] == str(self.organization.id)
