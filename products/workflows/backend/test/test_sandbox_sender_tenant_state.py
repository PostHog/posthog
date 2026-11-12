from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from structlog.testing import capture_logs

from products.workflows.backend.facade.tasks import sync_sandbox_sender_tenant_state
from products.workflows.backend.models import SandboxSenderTenantState
from products.workflows.backend.tests.fakes.ses_endpoint import FakeSesEndpoint

TENANT = "posthog-sandbox"
TENANT_ARN = "arn:aws:ses:us-east-1:123456789012:tenant/posthog-sandbox/abc"


@override_settings(SES_SANDBOX_TENANT_NAME=TENANT)
class TestSyncSandboxSenderTenantState(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.ses = self.enterContext(FakeSesEndpoint().installed())

    @parameterized.expand(
        [
            ("aggregate_wins_over_tenant_status", "ENABLED", "DISABLED", "DISABLED"),
            ("no_reputation_entity_yet", "ENABLED", None, "ENABLED"),
            ("missing_tenant", None, None, "UNKNOWN"),
        ]
    )
    def test_mirrors_the_tenant_status(
        self, _name: str, tenant_status: str | None, aggregate: str | None, expected: str
    ) -> None:
        if tenant_status is not None:
            self.ses.add_tenant(TENANT, sending_status=tenant_status, arn=TENANT_ARN)
        if aggregate is not None:
            self.ses.reputation_aggregates[TENANT_ARN] = aggregate

        sync_sandbox_sender_tenant_state()

        state = SandboxSenderTenantState.objects.get(tenant_name=TENANT)
        assert state.sending_status == expected
        assert state.synced_at is not None and timezone.now() - state.synced_at < timedelta(minutes=1)

    @parameterized.expand(
        [
            ("failed_read", timedelta(minutes=-5), True),
            ("later_run_already_stored_a_newer_status", timedelta(minutes=5), False),
        ]
    )
    def test_keeps_the_stored_status(self, _name: str, stored_offset: timedelta, read_fails: bool) -> None:
        synced_at = timezone.now() + stored_offset
        SandboxSenderTenantState.objects.create(tenant_name=TENANT, sending_status="ENABLED", synced_at=synced_at)
        self.ses.add_tenant(TENANT, sending_status="DISABLED")
        self.ses.denied = read_fails

        sync_sandbox_sender_tenant_state()

        state = SandboxSenderTenantState.objects.get(tenant_name=TENANT)
        assert (state.sending_status, state.synced_at) == ("ENABLED", synced_at)

    @override_settings(SES_SANDBOX_TENANT_NAME="")
    def test_does_nothing_without_a_sandbox_tenant(self) -> None:
        with capture_logs() as logs:
            sync_sandbox_sender_tenant_state()

        assert self.ses.requests == []
        assert logs == []
        assert not SandboxSenderTenantState.objects.exists()
