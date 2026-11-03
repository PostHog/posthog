from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import jwt
from parameterized import parameterized

from posthog.models import Organization, Team

from products.signals.backend.models import SignalSpend
from products.signals.backend.rated_usage_tasks import enqueue_signals_rated_usage, report_signals_rated_usage
from products.signals.backend.spend_billing import get_signals_spend_billing_credits_by_team
from products.signals.backend.test.test_billing import _at

from ee.billing.billing_manager import BillingManager
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

    def _spend(self, amount: str, *, team: Team | None = None, day: int = 10, exempt: bool = False) -> None:
        with time_machine.travel(_at(day), tick=False):
            SignalSpend.objects.for_team((team or self.team).id).create(
                team=team or self.team,
                signal_id=uuid4(),
                kind=SignalSpend.Kind.AD_HOC,
                spend=Decimal(amount),
                finalized_at=_at(day),
                billing_exempt=exempt,
            )

    @patch("ee.billing.billing_manager.http_session.post")
    def test_direct_report_matches_meter_and_replays_the_same_day(self, post: MagicMock) -> None:
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

        expected = {"items": [{"team_id": self.team.id, "product": "inbox_usage", "day": "2026-06-10", "cents": 3}]}
        assert dict(get_signals_spend_billing_credits_by_team(_at(10, 0), _at(11, 0), self.organization.id)) == {
            self.team.id: 3
        }
        assert post.call_count == 2
        for call in post.call_args_list:
            assert call.args[0].endswith("/api/rated-usage")
            assert call.kwargs["json"] == expected
            assert call.kwargs["timeout"] == 30
            token = call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
            claims = jwt.decode(token, "synthetic-secret", algorithms=["HS256"], audience="posthog:license-key")
            assert claims["organization_id"] == str(self.organization.id)
            assert claims["service_action"] == "rated_usage"
            assert "distinct_id" not in claims

    @patch("ee.billing.billing_manager.http_session.post")
    def test_report_respects_the_endpoint_batch_limit(self, post: MagicMock) -> None:
        teams = Team.objects.bulk_create(
            [Team(organization=self.organization, project=self.team.project) for _ in range(1001)]
        )
        SignalSpend.objects.unscoped().bulk_create(
            [
                SignalSpend(team=team, signal_id=uuid4(), kind=SignalSpend.Kind.AD_HOC, spend=1, finalized_at=_at(10))
                for team in teams
            ]
        )
        post.side_effect = lambda *args, **kwargs: MagicMock(
            status_code=200, json=lambda: {"results": ["created"] * len(kwargs["json"]["items"])}
        )
        report_signals_rated_usage.run(str(self.organization.id), "2026-06-10")
        assert [len(call.kwargs["json"]["items"]) for call in post.call_args_list] == [1000, 1]
        assert {item["team_id"] for call in post.call_args_list for item in call.kwargs["json"]["items"]} == {
            team.id for team in teams
        }

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
        response = MagicMock(status_code=status, json=lambda: body, ok=status == 200)
        with patch("ee.billing.billing_manager.http_session.post", return_value=response), pytest.raises(Exception):
            BillingManager(self.license).record_rated_usage(
                self.organization,
                [{"team_id": self.team.id, "product": "inbox_usage", "day": "2026-06-10", "cents": 3}],
            )

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
        with patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as enqueue:
            enqueue_signals_rated_usage.run()
        assert [call.args for call in enqueue.call_args_list] == [
            (str(self.organization.id), "2026-06-10"),
            (str(self.organization.id), "2026-06-11"),
        ]
        with patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as enqueue:
            enqueue_signals_rated_usage.run(day=date(2026, 6, 10).isoformat())
        enqueue.assert_called_once_with(str(self.organization.id), "2026-06-10")

    def test_sweep_delivers_unsnapshotted_usage_after_an_undated_default_plan(self) -> None:
        self._spend("25")
        self.organization.usage = {
            "signals_spend_credits": {"billing_cutover_date": "2026-06-10", "usage": 0, "limit": 0}
        }
        self.organization.save(update_fields=["usage"])
        with patch("products.signals.backend.rated_usage_tasks.report_signals_rated_usage.delay") as enqueue:
            enqueue_signals_rated_usage.run()
        enqueue.assert_called_once_with(str(self.organization.id), "2026-06-10")
        with patch("ee.billing.billing_manager.http_session.post") as post:
            post.return_value = MagicMock(status_code=200, json=lambda: {"results": ["created"]})
            report_signals_rated_usage.run(*enqueue.call_args.args)
        post.assert_called_once()
        assert post.call_args.kwargs["json"]["items"][0]["cents"] > 0

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
        post.assert_called_once()
        assert post.call_args.kwargs["json"] == original_payload
        token = post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(token, "synthetic-secret", algorithms=["HS256"], audience="posthog:license-key")
        assert claims["organization_id"] == str(self.organization.id)
