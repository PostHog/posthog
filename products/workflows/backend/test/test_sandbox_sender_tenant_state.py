from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from botocore.exceptions import ClientError
from parameterized import parameterized

from products.workflows.backend.facade.tasks import sync_sandbox_sender_tenant_state
from products.workflows.backend.models import SandboxSenderTenantState

TENANT = "posthog-sandbox"
TENANT_ARN = "arn:aws:ses:us-east-1:123456789012:tenant/posthog-sandbox/abc"


def _not_found() -> ClientError:
    return ClientError({"Error": {"Code": "NotFoundException"}}, "GetTenant")


@override_settings(SES_SANDBOX_TENANT_NAME=TENANT)
class TestSyncSandboxSenderTenantState(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("products.workflows.backend.providers.ses.boto3.client")
        self.ses = patcher.start().return_value
        self.addCleanup(patcher.stop)

    @parameterized.expand(
        [
            # The reputation aggregate folds in AWS-side pauses, so it wins over the tenant's own status.
            ("aggregate_status", {"SendingStatus": "ENABLED", "TenantArn": TENANT_ARN}, "DISABLED", "DISABLED"),
            ("no_reputation_entity_yet", {"SendingStatus": "ENABLED", "TenantArn": TENANT_ARN}, None, "ENABLED"),
            ("missing_tenant", None, None, "UNKNOWN"),
        ]
    )
    def test_mirrors_the_tenant_status(
        self, _name: str, tenant: dict | None, aggregate: str | None, expected: str
    ) -> None:
        if tenant is None:
            self.ses.get_tenant.side_effect = _not_found()
        else:
            self.ses.get_tenant.return_value = {"Tenant": tenant}
        if aggregate is None:
            self.ses.get_reputation_entity.side_effect = _not_found()
        else:
            self.ses.get_reputation_entity.return_value = {"ReputationEntity": {"SendingStatusAggregate": aggregate}}

        sync_sandbox_sender_tenant_state()

        state = SandboxSenderTenantState.objects.get(tenant_name=TENANT)
        assert state.sending_status == expected
        assert state.synced_at is not None and timezone.now() - state.synced_at < timedelta(minutes=1)

    @parameterized.expand(
        [
            ("failed_read", timedelta(minutes=-5), True),
            # A run that read the tenant before another run finished must not roll its status back.
            ("newer_status_already_stored", timedelta(minutes=5), False),
        ]
    )
    def test_keeps_the_stored_status(self, _name: str, stored_offset: timedelta, read_fails: bool) -> None:
        synced_at = timezone.now() + stored_offset
        SandboxSenderTenantState.objects.create(tenant_name=TENANT, sending_status="ENABLED", synced_at=synced_at)
        if read_fails:
            self.ses.get_tenant.side_effect = ClientError({"Error": {"Code": "ThrottlingException"}}, "GetTenant")
        else:
            self.ses.get_tenant.return_value = {"Tenant": {"SendingStatus": "DISABLED"}}

        sync_sandbox_sender_tenant_state()

        state = SandboxSenderTenantState.objects.get(tenant_name=TENANT)
        assert (state.sending_status, state.synced_at) == ("ENABLED", synced_at)

    @override_settings(SES_SANDBOX_TENANT_NAME="")
    def test_does_nothing_without_a_sandbox_tenant(self) -> None:
        sync_sandbox_sender_tenant_state()

        self.ses.get_tenant.assert_not_called()
        assert not SandboxSenderTenantState.objects.exists()
