from datetime import timedelta
from io import StringIO
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization

from products.feature_flags.backend.facade.flags import get_organization_flag_evaluations_mode
from products.feature_flags.backend.flag_evaluations_mode import (
    OrganizationModeChange,
    set_organization_flag_evaluations_mode,
)
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig
from products.feature_flags.backend.models.team_feature_flags_config import FlagEvaluationsMode


class TestSetFlagEvaluationsMode(BaseTest):
    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("set_flag_evaluations_mode", *args, stdout=out)
        return out.getvalue()

    def _stored_mode(self, organization: Organization) -> int | None:
        return (
            OrganizationFeatureFlagsConfig.objects.filter(organization=organization)
            .values_list("flag_evaluations_mode", flat=True)
            .first()
        )

    def _store_mode(self, organization: Organization, mode: FlagEvaluationsMode) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=organization, defaults={"flag_evaluations_mode": mode}
        )

    def test_an_organization_without_a_row_gets_one_at_the_target(self) -> None:
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).delete()

        self._run("--mode", "1", "--organization-id", str(self.organization.id))

        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.READ_FLAG_EVALUATIONS)

    def test_dry_run_reports_and_writes_nothing(self) -> None:
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).delete()

        output = self._run("--mode", "1", "--organization-id", str(self.organization.id), "--dry-run")

        self.assertIn(f"organization {self.organization.id}", output)
        self.assertIn("mode 0 -> 1", output)
        self.assertIn("Would set mode 1 on 1 organization(s).", output)
        self.assertIsNone(self._stored_mode(self.organization))

    @time_machine.travel("2026-09-01T12:00:00Z", tick=False)
    def test_created_after_selects_only_newer_organizations(self) -> None:
        cutoff = timezone.now() - timedelta(minutes=5)
        Organization.objects.filter(id=self.organization.id).update(created_at=cutoff - timedelta(days=1))
        new_organization = Organization.objects.create(name="New organization")

        self._run("--mode", "1", "--organizations-created-after", cutoff.isoformat())

        self.assertEqual(
            get_organization_flag_evaluations_mode(new_organization.id), FlagEvaluationsMode.READ_FLAG_EVALUATIONS
        )
        self.assertEqual(get_organization_flag_evaluations_mode(self.organization.id), FlagEvaluationsMode.EVENTS)

    @parameterized.expand(
        [
            (
                "keeps_a_higher_mode_by_default",
                (),
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                "Left 1 organization(s) above mode 1.",
            ),
            (
                "lowers_it_with_allow_downgrade",
                ("--allow-downgrade",),
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                "Set mode 1 on 1 organization(s).",
            ),
        ]
    )
    def test_downgrade_guard(
        self, _name: str, extra_args: tuple[str, ...], expected_mode: int, expected_output: str
    ) -> None:
        self._store_mode(self.organization, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

        output = self._run("--mode", "1", "--organization-id", str(self.organization.id), *extra_args)

        self.assertEqual(get_organization_flag_evaluations_mode(self.organization.id), expected_mode)
        self.assertIn(expected_output, output)

    def test_a_raise_after_the_read_is_not_overwritten(self) -> None:
        self._store_mode(self.organization, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

        # The stale read stands in for a staff write that raises the organization between the
        # helper's read and its write.
        with patch(
            "products.feature_flags.backend.flag_evaluations_mode.get_organization_flag_evaluations_mode",
            return_value=FlagEvaluationsMode.EVENTS,
        ):
            change = set_organization_flag_evaluations_mode(
                self.organization, FlagEvaluationsMode.READ_FLAG_EVALUATIONS, allow_downgrade=False, dry_run=False
            )

        self.assertFalse(change.changed)
        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

    def test_unknown_organization_id_fails_before_writing(self) -> None:
        missing_id = "00000000-0000-0000-0000-000000000000"

        with self.assertRaisesMessage(CommandError, missing_id):
            self._run("--mode", "1", "--organization-id", str(self.organization.id), "--organization-id", missing_id)

        self.assertEqual(get_organization_flag_evaluations_mode(self.organization.id), FlagEvaluationsMode.EVENTS)

    def test_a_failure_partway_leaves_every_organization_unchanged(self) -> None:
        second = Organization.objects.create(name="Second organization")

        def fail_on_second(organization: Organization, *args: Any, **kwargs: Any) -> OrganizationModeChange:
            if organization.id == second.id:
                raise RuntimeError("write failed")
            return set_organization_flag_evaluations_mode(organization, *args, **kwargs)

        with (
            patch(
                "products.feature_flags.backend.management.commands.set_flag_evaluations_mode.set_organization_flag_evaluations_mode",
                side_effect=fail_on_second,
            ),
            self.assertRaises(RuntimeError),
        ):
            self._run(
                "--mode", "1", "--organization-id", str(self.organization.id), "--organization-id", str(second.id)
            )

        self.assertEqual(get_organization_flag_evaluations_mode(self.organization.id), FlagEvaluationsMode.EVENTS)
