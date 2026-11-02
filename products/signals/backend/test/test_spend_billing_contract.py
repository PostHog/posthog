from datetime import timedelta
from typing import cast
from uuid import uuid4

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.organization import OrganizationUsageInfo

from products.signals.backend.billing import get_signals_billing_credits_by_team
from products.signals.backend.models import SignalSpend
from products.signals.backend.spend_billing import get_signals_spend_billing_credits_by_team
from products.signals.backend.test.test_billing import _at, _make_pr_run, _make_report

from ee.billing.quota_limiting import QuotaResource, self_driving_quota_resource, set_org_usage_summary


class TestSpendBillingContract(BaseTest):
    def test_partial_billing_sync_keeps_cutoff(self) -> None:
        self.organization.usage = {
            "signals_spend_credits": {
                "billing_start_date": "2026-06-10",
                "limit": 1000,
                "usage": 20,
            }
        }
        set_org_usage_summary(
            self.organization, cast(OrganizationUsageInfo, {"signals_credits": {"limit": 4500, "usage": 1500}})
        )
        assert self.organization.usage["signals_spend_credits"]["billing_start_date"] == "2026-06-10"
        with time_machine.travel(_at(9), tick=False):
            assert self_driving_quota_resource(self.organization) == QuotaResource.SIGNALS_CREDITS
        with time_machine.travel(_at(10, 0), tick=False):
            assert self_driving_quota_resource(self.organization) == QuotaResource.SIGNALS_SPEND_CREDITS

    @parameterized.expand([("original", False), ("after_plan_cleanup", True)])
    def test_distinct_meters_use_billing_cutoff_and_run_age(self, _name: str, cleanup: bool) -> None:
        self.organization.usage = {"signals_spend_credits": {"billing_start_date": "2026-06-10", "limit": 1000}}
        self.organization.save(update_fields=["usage"])
        with time_machine.travel(_at(9), tick=False):
            old_report = _make_report(self.team)
            legacy_report = _make_report(self.team)
            SignalSpend.objects.for_team(self.team.id).create(
                team=self.team,
                signal_id=uuid4(),
                kind=SignalSpend.Kind.AD_HOC,
                spend=500,
                finalized_at=_at(10),
            )
        _make_pr_run(self.team, legacy_report, created_at=_at(9))
        _make_pr_run(self.team, old_report, created_at=_at(10))
        with time_machine.travel(_at(10), tick=False):
            SignalSpend.objects.for_team(self.team.id).create(
                team=self.team,
                signal_id=uuid4(),
                kind=SignalSpend.Kind.AD_HOC,
                spend=25,
                finalized_at=_at(10),
            )
        if cleanup:
            with time_machine.travel(_at(10), tick=False):
                set_org_usage_summary(
                    self.organization,
                    cast(
                        OrganizationUsageInfo,
                        {
                            "signals_spend_credits": {"billing_start_date": "2026-06-01", "limit": 1000, "usage": 25},
                            "events": {"limit": 100, "usage": 12},
                        },
                    ),
                )
            assert self.organization.usage["signals_spend_credits"]["billing_start_date"] == "2026-06-01"
            assert self.organization.usage["signals_spend_credits"]["billing_cutover_date"] == "2026-06-10"
            assert self.organization.usage["events"]["usage"] == 12
            self.organization.save(update_fields=["usage"])
        with patch("posthoganalytics.get_feature_flag", side_effect=RuntimeError("unavailable")):
            assert dict(get_signals_billing_credits_by_team(_at(9, 0), _at(11, 0))) == {self.team.id: 1500}
            assert dict(get_signals_spend_billing_credits_by_team(_at(9, 0), _at(11, 0))) == {self.team.id: 25}
            assert dict(get_signals_billing_credits_by_team(_at(10, 0), _at(11, 0))) == {}

    @parameterized.expand([("missing", {}), ("default_plan", {"usage": 0, "limit": 0})])
    def test_unenrolled_org_reports_only_legacy_usage(self, _name: str, spend_usage: dict) -> None:
        set_org_usage_summary(
            self.organization,
            cast(OrganizationUsageInfo, {"signals_spend_credits": spend_usage, "events": {"usage": 12, "limit": 100}}),
        )
        self.organization.save(update_fields=["usage"])
        assert self_driving_quota_resource(self.organization) == QuotaResource.SIGNALS_CREDITS
        assert self.organization.usage["events"]["usage"] == 12
        with time_machine.travel(_at(10), tick=False):
            report = _make_report(self.team)
            _make_pr_run(self.team, report, created_at=_at(10))
            SignalSpend.objects.for_team(self.team.id).create(
                team=self.team,
                signal_id=uuid4(),
                kind=SignalSpend.Kind.AD_HOC,
                spend=25,
                finalized_at=_at(10),
            )
        assert dict(get_signals_spend_billing_credits_by_team(_at(10, 0), _at(10, 0) + timedelta(days=1))) == {}
        assert dict(get_signals_billing_credits_by_team(_at(10, 0), _at(11, 0))) == {self.team.id: 1500}

    @parameterized.expand([(None,), ("20260610",), ("invalid",)])
    def test_malformed_plan_date_is_rejected(self, cutoff: str | None) -> None:
        with pytest.raises(ValueError):
            set_org_usage_summary(
                self.organization,
                cast(OrganizationUsageInfo, {"signals_spend_credits": {"billing_start_date": cutoff}}),
            )

    @parameterized.expand([("initial", None), ("rescheduled", "2026-06-11")])
    @time_machine.travel(_at(9), tick=False)
    def test_upcoming_cutover_tracks_plan_schedule(self, _name: str, previous_cutoff: str | None) -> None:
        self.organization.usage = (
            {"signals_spend_credits": {"billing_start_date": previous_cutoff}} if previous_cutoff else {}
        )
        set_org_usage_summary(
            self.organization,
            cast(
                OrganizationUsageInfo,
                {"signals_spend_credits": {"billing_start_date": "2026-06-10", "limit": 1000, "usage": 0}},
            ),
        )
        assert self.organization.usage["signals_spend_credits"]["billing_cutover_date"] == "2026-06-10"
        assert self_driving_quota_resource(self.organization) == QuotaResource.SIGNALS_CREDITS
        with time_machine.travel(_at(10, 0), tick=False):
            assert self_driving_quota_resource(self.organization) == QuotaResource.SIGNALS_SPEND_CREDITS
