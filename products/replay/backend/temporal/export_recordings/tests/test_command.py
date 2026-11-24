import argparse
from datetime import date

import pytest
from posthog.test.base import BaseTest

from django.core.management.base import CommandError

from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus

from posthog.models import Organization, OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.replay.backend.management.commands.export_recordings_to_s3 import (
    _shard_list,
    check_approver,
    check_shard_rerun,
    record_export,
)
from products.replay.backend.temporal.export_recordings.quote import SelectionError, check_shard_selection
from products.replay.backend.temporal.export_recordings.types import ExportDestination, ExportRecordingsInput


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-08-01:1", ("2026-08-01:1",)),
        (" 2026-08-01:01 , 2026-08-02:10 ", ("2026-08-01:1", "2026-08-02:10")),
    ],
)
def test_shard_list_uses_the_spelling_the_workflow_compares(value: str, expected: tuple[str, ...]) -> None:
    assert _shard_list(value) == expected


@pytest.mark.parametrize("value", ["2026-08-01", "2026-08-01:-1", "2026-13-01:1", "2026-08-01:x", "", " , "])
def test_shard_list_rejects_malformed_names(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _shard_list(value)


@pytest.mark.parametrize(
    "session_ids,accepted",
    [
        (["a" * 36] * 1000, True),
        (["a" * 36] * 100_001, False),
    ],
)
def test_a_shard_holds_at_most_the_session_cap(session_ids: list[str], accepted: bool) -> None:
    if accepted:
        check_shard_selection(date(2026, 8, 1), 0, session_ids)
    else:
        with pytest.raises(SelectionError):
            check_shard_selection(date(2026, 8, 1), 0, session_ids)


@pytest.mark.parametrize(
    "last_run_status,accepted",
    [
        (WorkflowExecutionStatus.FAILED, True),
        (None, False),
        (WorkflowExecutionStatus.COMPLETED, False),
        (WorkflowExecutionStatus.RUNNING, False),
    ],
)
def test_shards_rerun_only_after_a_failed_run(last_run_status: WorkflowExecutionStatus | None, accepted: bool) -> None:
    if accepted:
        check_shard_rerun(last_run_status)
    else:
        with pytest.raises(CommandError):
            check_shard_rerun(last_run_status)


class TestExportApproval(BaseTest):
    @parameterized.expand(
        [
            ("admin", OrganizationMembership.Level.ADMIN, True),
            ("owner", OrganizationMembership.Level.OWNER, True),
            ("member", OrganizationMembership.Level.MEMBER, False),
        ]
    )
    def test_only_an_admin_of_the_teams_organization_approves(
        self, _: str, level: OrganizationMembership.Level, accepted: bool
    ) -> None:
        User.objects.create_and_join(self.organization, "approver@example.com", None, level=level)

        if accepted:
            check_approver(self.organization.id, "Approver@example.com")
        else:
            with pytest.raises(CommandError):
                check_approver(self.organization.id, "approver@example.com")

    def test_a_deactivated_admin_does_not_approve(self) -> None:
        user = User.objects.create_and_join(
            self.organization, "approver@example.com", None, level=OrganizationMembership.Level.ADMIN
        )
        user.is_active = False
        user.save()

        with pytest.raises(CommandError):
            check_approver(self.organization.id, "approver@example.com")

    def test_an_admin_of_another_organization_does_not_approve(self) -> None:
        other = Organization.objects.create(name="Other")
        User.objects.create_and_join(other, "approver@example.com", None, level=OrganizationMembership.Level.ADMIN)

        with pytest.raises(CommandError):
            check_approver(self.organization.id, "approver@example.com")

    def test_a_started_export_shows_its_destination_in_the_activity_log(self) -> None:
        destination = ExportDestination(
            role_arn="arn:aws:iam::123456789012:role/r", bucket="customer", region="us-east-1", prefix="exports"
        )
        workflow_input = ExportRecordingsInput(
            team_id=self.team.pk,
            destination=destination,
            quote_id="q1",
            run_id="run-1",
            date_from="2026-08-01",
            date_to="2026-08-02",
            session_ids_prefix="ids",
            shards_per_day=1,
            max_parallel_shards=1,
        )

        record_export(self.organization.id, workflow_input, "export-recordings-1-q1", "approver@example.com")

        entry = ActivityLog.objects.get(team_id=self.team.pk, scope="Replay", activity="exported")
        assert entry.is_system and entry.detail is not None
        assert entry.detail["trigger"]["payload"] == {
            "role_arn": "arn:aws:iam::123456789012:role/r",
            "bucket": "customer",
            "prefix": "exports",
            "region": "us-east-1",
            "kms_key_id": None,
            "run_id": "run-1",
            "approved_by": "approver@example.com",
        }
