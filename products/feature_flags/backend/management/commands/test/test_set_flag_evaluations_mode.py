from datetime import timedelta
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import QuerySet
from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.feature_flags.backend.models.team_feature_flags_config import FlagEvaluationsMode, TeamFeatureFlagsConfig


class TestSetFlagEvaluationsMode(BaseTest):
    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("set_flag_evaluations_mode", *args, stdout=out)
        return out.getvalue()

    def _modes(self, organization: Organization) -> dict[int, int | None]:
        stored = dict(
            TeamFeatureFlagsConfig.objects.filter(team__organization=organization).values_list(
                "team_id", "flag_evaluations_mode"
            )
        )
        return {team.id: stored.get(team.id) for team in Team.objects.filter(organization=organization)}

    @parameterized.expand(
        [
            ("sibling_below_the_target", FlagEvaluationsMode.EVENTS, FlagEvaluationsMode.READ_FLAG_EVALUATIONS),
            (
                "sibling_above_the_target",
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            ),
        ]
    )
    def test_a_team_without_a_config_row_lands_on_the_target(
        self, _name, sibling_mode: int, expected_sibling_mode: int
    ) -> None:
        legacy_team = Team.objects.create(organization=self.organization, name="Legacy")
        TeamFeatureFlagsConfig.objects.filter(team=legacy_team).delete()
        TeamFeatureFlagsConfig.objects.filter(team=self.team).update(flag_evaluations_mode=sibling_mode)

        self._run("--mode", "1", "--organization-id", str(self.organization.id))

        self.assertEqual(
            self._modes(self.organization),
            {self.team.id: expected_sibling_mode, legacy_team.id: FlagEvaluationsMode.READ_FLAG_EVALUATIONS},
        )

    def test_dry_run_reports_and_writes_nothing(self) -> None:
        output = self._run("--mode", "1", "--organization-id", str(self.organization.id), "--dry-run")

        self.assertIn(f"organization {self.organization.id}", output)
        self.assertIn("Would set mode 1 on 1 team(s).", output)
        self.assertEqual(self._modes(self.organization), {self.team.id: FlagEvaluationsMode.EVENTS})

    def test_created_after_selects_only_newer_organizations(self) -> None:
        cutoff = timezone.now() - timedelta(minutes=5)
        Organization.objects.filter(id=self.organization.id).update(created_at=cutoff - timedelta(days=1))
        new_organization = Organization.objects.create(name="New organization")
        new_team = Team.objects.create(organization=new_organization, name="New team")

        self._run("--mode", "1", "--organizations-created-after", cutoff.isoformat())

        self.assertEqual(self._modes(new_organization), {new_team.id: FlagEvaluationsMode.READ_FLAG_EVALUATIONS})
        self.assertEqual(self._modes(self.organization), {self.team.id: FlagEvaluationsMode.EVENTS})

    @parameterized.expand(
        [
            ("keeps_a_higher_mode_by_default", (), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY),
            ("lowers_it_with_allow_downgrade", ("--allow-downgrade",), FlagEvaluationsMode.READ_FLAG_EVALUATIONS),
        ]
    )
    def test_downgrade_guard(self, _name, extra_args: tuple[str, ...], expected_mode: int) -> None:
        TeamFeatureFlagsConfig.objects.filter(team=self.team).update(
            flag_evaluations_mode=FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
        )

        self._run("--mode", "1", "--organization-id", str(self.organization.id), *extra_args)

        self.assertEqual(self._modes(self.organization), {self.team.id: expected_mode})

    def test_a_run_that_stops_partway_leaves_the_organization_unchanged(self) -> None:
        first = Team.objects.create(organization=self.organization, name="First")
        second = Team.objects.create(organization=self.organization, name="Second")
        TeamFeatureFlagsConfig.objects.filter(team__in=[first, second]).delete()
        original_update = QuerySet.update

        # The INSERT of the missing rows runs first, so failing the UPDATE shows that those rows roll back.
        def fail_on_config_update(queryset: QuerySet, **kwargs: Any) -> int:
            if queryset.model is TeamFeatureFlagsConfig:
                raise RuntimeError("write failed")
            return original_update(queryset, **kwargs)

        with (
            patch.object(QuerySet, "update", autospec=True, side_effect=fail_on_config_update),
            self.assertRaises(RuntimeError),
        ):
            self._run("--mode", "1", "--organization-id", str(self.organization.id))

        self.assertEqual(
            self._modes(self.organization), {self.team.id: FlagEvaluationsMode.EVENTS, first.id: None, second.id: None}
        )

    def test_unknown_organization_id_fails_before_writing(self) -> None:
        missing_id = "00000000-0000-0000-0000-000000000000"

        with self.assertRaisesMessage(CommandError, missing_id):
            self._run("--mode", "1", "--organization-id", str(self.organization.id), "--organization-id", missing_id)

        self.assertEqual(self._modes(self.organization), {self.team.id: FlagEvaluationsMode.EVENTS})
