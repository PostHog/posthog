from dataclasses import replace

import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.models import Organization, Team, User

from products.tasks.backend.facade.profiles import get_task_profile
from products.tasks.backend.logic.services.compute_quota import (
    ComputeQuotaDenialReason,
    ai_credits_compute_origins,
    get_compute_quota_denial_reason,
    is_billable_compute,
    is_compute_quota_exhausted,
    is_task_billable_compute,
)
from products.tasks.backend.models import Task, TaskClientProvenance


@pytest.mark.django_db
class TestComputeQuota:
    @pytest.fixture(autouse=True)
    def setup(self):
        organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=organization, name="test")

    def task(self, **overrides):
        defaults = {
            "team": self.team,
            "title": "task",
            "description": "task",
            "origin_product": Task.OriginProduct.USER_CREATED,
            "client_provenance": TaskClientProvenance.POSTHOG_DESKTOP,
        }
        defaults.update(overrides)
        return Task.objects.create(**defaults)

    @override_settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=False)
    @patch("products.tasks.backend.logic.services.compute_quota._is_posthog_code_quota_limited", return_value=True)
    def test_inactive_enforcement_never_blocks(self, limited):
        assert not is_compute_quota_exhausted(self.task())
        limited.assert_not_called()

    @override_settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=False)
    def test_any_deactivated_org_blocks_even_with_enforcement_off(self):
        self.team.organization.is_active = False
        self.team.organization.is_not_active_reason = "Past due invoice"
        self.team.organization.save()

        assert is_compute_quota_exhausted(self.task())
        assert get_compute_quota_denial_reason(self.task()) == ComputeQuotaDenialReason.ORGANIZATION_DEACTIVATED

    @override_settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True)
    @patch("products.tasks.backend.logic.services.compute_quota._is_posthog_code_quota_limited")
    def test_combined_posthog_code_quota_controls_billable_task(self, limited):
        task = self.task()
        limited.side_effect = [True, False]

        assert is_compute_quota_exhausted(task)
        assert not is_compute_quota_exhausted(task)
        limited.assert_called_with(self.team.api_token)

    @override_settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True)
    @patch("products.tasks.backend.logic.services.compute_quota._is_posthog_code_quota_limited", return_value=True)
    def test_staff_task_bypasses_compute_quota(self, limited):
        staff_user = User.objects.create(email="staff@example.com", is_staff=True)

        assert not is_compute_quota_exhausted(self.task(created_by=staff_user))
        limited.assert_not_called()

    @override_settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True)
    def test_deactivated_organization_still_blocks_staff_task(self):
        staff_user = User.objects.create(email="staff@example.com", is_staff=True)
        self.team.organization.is_active = False
        self.team.organization.save(update_fields=["is_active"])

        assert (
            get_compute_quota_denial_reason(self.task(created_by=staff_user))
            == ComputeQuotaDenialReason.ORGANIZATION_DEACTIVATED
        )

    @override_settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True)
    @patch(
        "products.tasks.backend.logic.services.compute_quota._is_posthog_code_quota_limited",
        side_effect=ConnectionError,
    )
    def test_unavailable_quota_state_fails_open(self, _limited):
        assert not is_compute_quota_exhausted(self.task())

    @pytest.mark.parametrize(
        "origin,provenance",
        [
            (Task.OriginProduct.SLACK, TaskClientProvenance.POSTHOG_DESKTOP),
            (Task.OriginProduct.SIGNAL_REPORT, TaskClientProvenance.POSTHOG_DESKTOP),
            (Task.OriginProduct.USER_CREATED, None),
        ],
    )
    def test_non_billable_origins_are_ineligible(self, origin, provenance):
        assert not is_task_billable_compute(self.task(origin_product=origin, client_provenance=provenance))

    @pytest.mark.parametrize("origin", [Task.OriginProduct.USER_CREATED, Task.OriginProduct.SPACE_SETUP])
    @pytest.mark.parametrize("provenance", list(TaskClientProvenance))
    def test_first_party_client_origins_are_billable(self, origin, provenance):
        assert is_task_billable_compute(self.task(origin_product=origin, client_provenance=provenance))

    def test_unknown_origin_is_ineligible(self):
        assert not is_billable_compute(origin_product=None, client_provenance=TaskClientProvenance.POSTHOG_DESKTOP)

    @pytest.mark.parametrize(
        "bills_compute,provenance,billable",
        [
            (True, TaskClientProvenance.POSTHOG_DESKTOP, True),
            (False, TaskClientProvenance.POSTHOG_DESKTOP, False),
            (True, None, False),
        ],
    )
    def test_profiled_task_bills_compute_by_its_profile(self, bills_compute, provenance, billable):
        profile = replace(get_task_profile("business_knowledge"), key="test.billing", bills_compute=bills_compute)

        with patch.dict("products.tasks.backend.facade.profiles._profiles", {profile.key: profile}):
            assert is_task_billable_compute(self.task(profile=profile.key, client_provenance=provenance)) is billable

    @pytest.mark.parametrize(
        "origin,provenance",
        [
            (Task.OriginProduct.POSTHOG_AI, TaskClientProvenance.POSTHOG_WEB),
            # Slack tasks carry no client provenance.
            (Task.OriginProduct.SLACK, None),
        ],
    )
    @override_settings(
        TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True, AI_CREDITS_COMPUTE_BILLED_ORIGINS=["posthog_ai", "slack"]
    )
    @patch("products.tasks.backend.logic.services.compute_quota._is_posthog_code_quota_limited", return_value=False)
    @patch("products.tasks.backend.logic.services.compute_quota._is_ai_credits_quota_limited")
    def test_ai_credits_quota_controls_ai_billed_origin(self, ai_limited, code_limited, origin, provenance):
        task = self.task(origin_product=origin, client_provenance=provenance)
        ai_limited.side_effect = [True, False]

        assert get_compute_quota_denial_reason(task) == ComputeQuotaDenialReason.COMPUTE_QUOTA_EXHAUSTED
        assert not is_compute_quota_exhausted(task)
        ai_limited.assert_called_with(self.team.api_token)
        code_limited.assert_not_called()

    @override_settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True)
    @patch("products.tasks.backend.logic.services.compute_quota._is_posthog_code_quota_limited", return_value=True)
    @patch("products.tasks.backend.logic.services.compute_quota._is_ai_credits_quota_limited", return_value=True)
    def test_ai_origin_is_unchecked_while_its_compute_is_not_billed(self, ai_limited, code_limited):
        task = self.task(
            origin_product=Task.OriginProduct.POSTHOG_AI, client_provenance=TaskClientProvenance.POSTHOG_WEB
        )

        assert not is_compute_quota_exhausted(task)
        ai_limited.assert_not_called()
        code_limited.assert_not_called()

    @override_settings(
        TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True, AI_CREDITS_COMPUTE_BILLED_ORIGINS=["posthog_ai", "slack"]
    )
    @patch("products.tasks.backend.logic.services.compute_quota._is_posthog_code_quota_limited", return_value=True)
    @patch("products.tasks.backend.logic.services.compute_quota._is_ai_credits_quota_limited", return_value=False)
    def test_desktop_task_stays_on_posthog_code_quota_with_ai_origins_billed(self, ai_limited, code_limited):
        assert is_compute_quota_exhausted(self.task())
        code_limited.assert_called_once_with(self.team.api_token)
        ai_limited.assert_not_called()

    @override_settings(AI_CREDITS_COMPUTE_BILLED_ORIGINS=["posthog_ai", "user_created", "space_setup"])
    def test_desktop_origins_can_never_bill_into_ai_credits(self):
        assert ai_credits_compute_origins() == frozenset({"posthog_ai"})
