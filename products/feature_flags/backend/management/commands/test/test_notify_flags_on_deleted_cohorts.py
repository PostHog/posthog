from io import StringIO
from operator import attrgetter
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.deleted_cohort_notices import (
    AffectedFlag,
    DeletedCohort,
    FlagOwner,
    build_notice,
    find_flags_on_deleted_cohorts,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notifications.backend.facade.api import NotificationType, SourceType, TargetType
from products.notifications.backend.facade.testing import stored_notifications_for_team
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

NOTICE_TEAM_ID = 42
SURVEY_ID = "0b1c5a52-6d1e-4c43-9a0e-5f2b8f8d1a01"
BETA_TESTERS = DeletedCohort(id=7, name="Beta testers", missing=False)


def _affected_flag(flag_id: int, key: str, owner: FlagOwner | None = None) -> AffectedFlag:
    return AffectedFlag(
        flag_id=flag_id,
        team_id=NOTICE_TEAM_ID,
        key=key,
        last_called_at=None,
        cohorts=(BETA_TESTERS,),
        owner=owner,
    )


class TestBuildNotice(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "one_plain_flag",
                [_affected_flag(101, "checkout-redesign")],
                {
                    "source_type": SourceType.FEATURE_FLAG,
                    "source_id": "101",
                    "resource_type": "feature_flag",
                    "resource_id": "101",
                    "title": "Feature flag targets a deleted cohort: checkout-redesign",
                    "body": (
                        "Flag 'checkout-redesign' targets the deleted cohort 'Beta testers'. The flag fails to "
                        "evaluate until you remove that condition or choose another cohort."
                    ),
                },
                [],
                [],
            ),
            (
                "one_survey_targeting_flag",
                [
                    _affected_flag(
                        102,
                        "survey-targeting-onboarding",
                        FlagOwner(kind="survey", id=SURVEY_ID, name="Onboarding feedback"),
                    )
                ],
                {
                    "source_type": SourceType.SURVEY,
                    "source_id": SURVEY_ID,
                    "resource_type": "survey",
                    "title": "Survey targets a deleted cohort: Onboarding feedback",
                },
                ["Survey 'Onboarding feedback' targets the deleted cohort 'Beta testers'."],
                [],
            ),
            (
                "six_plain_flags",
                [_affected_flag(110 + n, f"rollout-{n}") for n in range(1, 7)],
                {
                    "source_type": None,
                    "source_id": None,
                    "source_url": "/feature_flags",
                    "title": "6 feature flags target deleted cohorts",
                },
                ["flag 'rollout-1' (cohort 'Beta testers')", "and 1 more"],
                ["'rollout-6'"],
            ),
        ]
    )
    def test_build_notice_links_and_words_the_notice_for_what_it_lists(
        self,
        _name: str,
        flags: list[AffectedFlag],
        expected_fields: dict[str, Any],
        body_includes: list[str],
        body_excludes: list[str],
    ) -> None:
        expected = {
            "team_id": NOTICE_TEAM_ID,
            "notification_type": NotificationType.FEATURE_FLAG_FAILURE,
            "target_type": TargetType.TEAM,
            "target_id": str(NOTICE_TEAM_ID),
            "idempotency_key": "flags-deleted-cohort-notice",
            **expected_fields,
        }

        notice = build_notice(NOTICE_TEAM_ID, flags)

        assert {field: getattr(notice, field) for field in expected} == expected
        assert [fragment for fragment in body_includes if fragment not in notice.body] == []
        assert [fragment for fragment in body_excludes if fragment in notice.body] == []


class TestNotifyFlagsOnDeletedCohorts(BaseTest):
    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("notify_flags_on_deleted_cohorts", *args, stdout=out)
        return out.getvalue()

    def _cohort(self, name: str, *, team: Team | None = None, deleted: bool = False) -> Cohort:
        return Cohort.objects.create(team=team or self.team, name=name, deleted=deleted)

    def _flag(self, key: str, cohort: Cohort, **fields: Any) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            filters={
                "groups": [
                    {"properties": [{"key": "id", "type": "cohort", "value": cohort.id}], "rollout_percentage": 100}
                ]
            },
            **fields,
        )

    def test_finder_reports_active_flags_on_deleted_or_foreign_cohorts_only(self) -> None:
        deleted_cohort = self._cohort("Beta testers", deleted=True)
        other_project_cohort = self._cohort("Early adopters", team=Team.objects.create(organization=self.organization))
        on_deleted_cohort = self._flag("checkout-redesign", deleted_cohort)
        self._flag("pricing-page-v2", self._cohort("Power users"))
        on_other_project_cohort = self._flag("onboarding-checklist", other_project_cohort)
        self._flag("dark-mode", deleted_cohort, active=False)
        self._flag("legacy-search", deleted_cohort, deleted=True)
        survey = Survey.objects.create(
            team=self.team, name="Onboarding feedback", type="popover", targeting_flag=on_deleted_cohort
        )
        tour = ProductTour.objects.create(
            team=self.team, name="Welcome tour", internal_targeting_flag=on_other_project_cohort
        )

        result = find_flags_on_deleted_cohorts([self.team.id])

        # The notice goes to this project, so it must not name a cohort that another project owns.
        assert {team_id: sorted(flags, key=attrgetter("flag_id")) for team_id, flags in result.items()} == {
            self.team.id: [
                AffectedFlag(
                    flag_id=on_deleted_cohort.id,
                    team_id=self.team.id,
                    key="checkout-redesign",
                    last_called_at=None,
                    cohorts=(DeletedCohort(id=deleted_cohort.id, name="Beta testers", missing=False),),
                    owner=FlagOwner(kind="survey", id=str(survey.id), name="Onboarding feedback"),
                ),
                AffectedFlag(
                    flag_id=on_other_project_cohort.id,
                    team_id=self.team.id,
                    key="onboarding-checklist",
                    last_called_at=None,
                    cohorts=(DeletedCohort(id=other_project_cohort.id, name=None, missing=True),),
                    owner=FlagOwner(kind="product_tour", id=str(tour.id), name="Welcome tour"),
                ),
            ]
        }

    @parameterized.expand(
        [
            ("notifications_on", True, ["Feature flag targets a deleted cohort: checkout-redesign"]),
            ("notifications_off", False, []),
        ]
    )
    def test_dry_run_sends_nothing_and_send_notifies_the_team_once(
        self, _name: str, notifications_on: bool, expected_titles: list[str]
    ) -> None:
        self.enterContext(
            patch(
                "posthoganalytics.feature_enabled",
                side_effect=lambda flag, *args, **kwargs: notifications_on and flag == "real-time-notifications",
            )
        )
        self._flag("checkout-redesign", self._cohort("Beta testers", deleted=True))

        dry_run = self._run("--team-id", str(self.team.id))
        with self.assertRaises(CommandError):
            self._run("--send")

        assert stored_notifications_for_team(self.team.id) == []
        assert self.team.name in dry_run
        assert str(self.team.id) in dry_run

        first_send = self._run("--send", "--team-id", str(self.team.id))

        sent = stored_notifications_for_team(self.team.id)
        assert [notice.title for notice in sent] == expected_titles
        if not notifications_on:
            assert "not delivered" in first_send.lower()

        self._run("--send", "--team-id", str(self.team.id))

        assert stored_notifications_for_team(self.team.id) == sent
