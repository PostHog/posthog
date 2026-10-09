from datetime import timedelta

import pytest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.models import Organization, Team, User
from posthog.redis import get_client

from products.tasks.backend.facade.compute_quota import (
    cloud_agents_quota_denial,
    cloud_agents_quota_reset_at,
    list_teams_over_cloud_agents_quota_with_active_runs,
)
from products.tasks.backend.logic.services.compute_quota import (
    ComputeQuotaDenialReason,
    billing_product,
    get_compute_quota_denial_reason,
    is_billable_compute,
    is_compute_quota_exhausted,
    is_task_billable_compute,
)
from products.tasks.backend.models import Loop, Task, TaskClientProvenance, TaskRun

_POSTHOG_CODE_LIMITED = "products.tasks.backend.logic.services.compute_quota._is_posthog_code_quota_limited"
_CLOUD_AGENTS_LIMITED = "products.tasks.backend.logic.services.compute_quota._is_cloud_agents_quota_limited"
_CLOUD_AGENTS_LIMITED_TEAMS = "products.tasks.backend.logic.services.compute_quota._cloud_agents_quota_limited_team_ids"


@pytest.mark.parametrize(
    "origin,provenance,loop_id,loop_internal,expected",
    [
        (Task.OriginProduct.CLOUD_AGENTS, TaskClientProvenance.CLOUD_AGENTS, None, None, "cloud_agents"),
        (Task.OriginProduct.CLOUD_AGENTS, None, None, None, None),
        (Task.OriginProduct.CLOUD_AGENTS, TaskClientProvenance.POSTHOG_DESKTOP, None, None, None),
        (Task.OriginProduct.USER_CREATED, TaskClientProvenance.CLOUD_AGENTS, None, None, None),
        (Task.OriginProduct.LOOP, TaskClientProvenance.CLOUD_AGENTS, 1, False, None),
        (Task.OriginProduct.USER_CREATED, TaskClientProvenance.POSTHOG_DESKTOP, None, None, "posthog_code"),
        (Task.OriginProduct.SPACE_SETUP, TaskClientProvenance.POSTHOG_DESKTOP, None, None, "posthog_code"),
        (Task.OriginProduct.LOOP, TaskClientProvenance.POSTHOG_DESKTOP, 1, False, "posthog_code"),
        (Task.OriginProduct.LOOP, TaskClientProvenance.POSTHOG_DESKTOP, 1, True, None),
        (Task.OriginProduct.LOOP, TaskClientProvenance.POSTHOG_DESKTOP, None, None, None),
        (Task.OriginProduct.SLACK, TaskClientProvenance.POSTHOG_DESKTOP, None, None, None),
        (Task.OriginProduct.USER_CREATED, None, None, None, None),
        (None, TaskClientProvenance.POSTHOG_DESKTOP, None, None, None),
    ],
)
def test_billing_product_matrix(origin, provenance, loop_id, loop_internal, expected):
    kwargs = {
        "origin_product": origin,
        "client_provenance": provenance,
        "source_loop_id": loop_id,
        "source_loop_internal": loop_internal,
    }
    assert billing_product(**kwargs) == expected
    assert is_billable_compute(**kwargs) is (expected == "posthog_code")


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
    def test_desktop_started_origins_are_billable(self, origin):
        assert is_task_billable_compute(
            self.task(origin_product=origin, client_provenance=TaskClientProvenance.POSTHOG_DESKTOP)
        )

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

    def cloud_agents_task(self, *, billed: bool = True, **overrides):
        return self.task(
            origin_product=Task.OriginProduct.CLOUD_AGENTS,
            client_provenance=TaskClientProvenance.CLOUD_AGENTS if billed else None,
            internal=True,
            **overrides,
        )

    @pytest.mark.parametrize("desktop_enforcement", [True, False])
    @override_settings(CLOUD_AGENTS_QUOTA_ENFORCEMENT_ENABLED=True)
    def test_cloud_agents_task_is_limited_by_its_own_resource_only(self, desktop_enforcement):
        with (
            override_settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=desktop_enforcement),
            patch(_POSTHOG_CODE_LIMITED, return_value=False) as posthog_code,
            patch(_CLOUD_AGENTS_LIMITED, return_value=True) as cloud_agents,
        ):
            reason = get_compute_quota_denial_reason(self.cloud_agents_task())

        assert reason == ComputeQuotaDenialReason.COMPUTE_QUOTA_EXHAUSTED
        cloud_agents.assert_called_once_with(self.team.api_token)
        posthog_code.assert_not_called()

    @override_settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True, CLOUD_AGENTS_QUOTA_ENFORCEMENT_ENABLED=True)
    def test_exhausted_cloud_agents_quota_does_not_limit_a_desktop_task(self):
        with patch(_POSTHOG_CODE_LIMITED, return_value=False), patch(_CLOUD_AGENTS_LIMITED, return_value=True):
            assert not is_compute_quota_exhausted(self.task())

    @pytest.mark.parametrize(
        "enforcement,billed",
        [(False, True), (True, False)],
        ids=["switch off", "unbilled internal run"],
    )
    def test_cloud_agents_task_is_not_quota_checked(self, enforcement, billed):
        with (
            override_settings(
                CLOUD_AGENTS_QUOTA_ENFORCEMENT_ENABLED=enforcement, TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True
            ),
            patch(_POSTHOG_CODE_LIMITED, return_value=True) as posthog_code,
            patch(_CLOUD_AGENTS_LIMITED, return_value=True) as cloud_agents,
        ):
            assert not is_compute_quota_exhausted(self.cloud_agents_task(billed=billed))

        posthog_code.assert_not_called()
        cloud_agents.assert_not_called()

    @pytest.mark.parametrize(
        "org_active,limited,enforcement,expected",
        [
            (True, True, True, "quota_exhausted"),
            (True, False, True, None),
            (True, True, False, None),
            (False, False, True, "organization_deactivated"),
            (False, False, False, "organization_deactivated"),
            (True, ConnectionError(), True, None),
        ],
    )
    def test_cloud_agents_quota_denial_codes(self, org_active, limited, enforcement, expected):
        self.team.organization.is_active = org_active
        self.team.organization.save(update_fields=["is_active"])

        with (
            override_settings(
                CLOUD_AGENTS_QUOTA_ENFORCEMENT_ENABLED=enforcement, TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=False
            ),
            patch(_CLOUD_AGENTS_LIMITED, side_effect=[limited]),
        ):
            assert cloud_agents_quota_denial(team_id=self.team.id) == expected

    def test_cloud_agents_quota_resets_at_the_billing_period_end(self):
        assert cloud_agents_quota_reset_at(team_id=self.team.id) is None

        self.team.organization.usage = {"period": ["2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"]}
        self.team.organization.save(update_fields=["usage"])

        reset_at = cloud_agents_quota_reset_at(team_id=self.team.id)
        assert reset_at is not None
        assert reset_at.isoformat() == "2026-11-01T00:00:00+00:00"

    @override_settings(CLOUD_AGENTS_QUOTA_ENFORCEMENT_ENABLED=True)
    def test_sweep_lists_only_limited_teams_with_an_active_billed_run(self):
        def team_with_run(name, *, billed=True, status=TaskRun.Status.IN_PROGRESS, org_active=True):
            organization = Organization.objects.create(name=name, is_active=org_active)
            team = Team.objects.create(organization=organization, name=name)
            task = Task.objects.create(
                team=team,
                title=name,
                description="",
                origin_product=Task.OriginProduct.CLOUD_AGENTS,
                client_provenance=TaskClientProvenance.CLOUD_AGENTS if billed else None,
                internal=True,
            )
            TaskRun.objects.create(task=task, team=team, status=status)
            return team

        limited = team_with_run("limited")
        within_quota = team_with_run("within quota")
        finished = team_with_run("finished", status=TaskRun.Status.COMPLETED)
        unbilled = team_with_run("unbilled", billed=False)
        deactivated = team_with_run("deactivated", org_active=False)
        TaskRun.objects.create(task=self.task(), team=self.team, status=TaskRun.Status.IN_PROGRESS)
        over_quota = {limited.id, finished.id, unbilled.id, self.team.id}

        with patch(_CLOUD_AGENTS_LIMITED_TEAMS, side_effect=lambda team_ids: over_quota & set(team_ids)) as lookup:
            assert list_teams_over_cloud_agents_quota_with_active_runs() == sorted([limited.id, deactivated.id])
        assert set(lookup.call_args.args[0]) == {limited.id, within_quota.id}

        with patch(_CLOUD_AGENTS_LIMITED_TEAMS, side_effect=ConnectionError):
            assert list_teams_over_cloud_agents_quota_with_active_runs() == [deactivated.id]

    @pytest.mark.parametrize(
        "limited_resource,expected_listed",
        [("cloud_agents_credits", True), ("posthog_code_credits", False)],
    )
    @override_settings(CLOUD_AGENTS_QUOTA_ENFORCEMENT_ENABLED=True)
    def test_sweep_reads_the_cloud_agents_resource(self, limited_resource, expected_listed):
        from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, add_limited_team_tokens

        resource = QuotaResource(limited_resource)
        TaskRun.objects.create(task=self.cloud_agents_task(), team=self.team, status=TaskRun.Status.QUEUED)
        limited_until = int((timezone.now() + timedelta(days=1)).timestamp())
        add_limited_team_tokens(
            resource, {self.team.api_token: limited_until}, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        try:
            listed = list_teams_over_cloud_agents_quota_with_active_runs()
        finally:
            get_client().zrem(
                f"{QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY.value}{resource.value}", self.team.api_token
            )

        assert (self.team.id in listed) is expected_listed
