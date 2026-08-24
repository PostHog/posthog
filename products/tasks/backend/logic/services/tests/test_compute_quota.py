import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.models import Organization, Team, User

from products.tasks.backend.logic.services.compute_quota import (
    ComputeQuotaDenialReason,
    get_compute_quota_denial_reason,
    is_billable_compute,
    is_compute_quota_exhausted,
    is_task_billable_compute,
)
from products.tasks.backend.models import Loop, Task, TaskClientProvenance


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

    def test_unknown_origin_is_ineligible(self):
        assert not is_billable_compute(
            origin_product=None,
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
            source_loop_id=None,
            source_loop_internal=None,
        )

    def test_only_direct_non_internal_desktop_loop_is_eligible(self):
        loop_defaults = {"team": self.team, "instructions": "run", "runtime_adapter": "agent"}
        user_loop = Loop.objects.unscoped().create(**loop_defaults, name="user", internal=False)
        internal_loop = Loop.objects.unscoped().create(**loop_defaults, name="internal", internal=True)

        assert is_task_billable_compute(self.task(origin_product=Task.OriginProduct.LOOP, loop=user_loop))
        assert not is_task_billable_compute(self.task(origin_product=Task.OriginProduct.LOOP, loop=internal_loop))
        assert not is_task_billable_compute(self.task(origin_product=Task.OriginProduct.LOOP))
