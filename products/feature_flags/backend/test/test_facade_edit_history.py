from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.activity_logging.activity_log import ActivityLog

from products.feature_flags.backend.facade.edit_history import FlagEditAuthor, flag_edits_since, served_strings_in_edits
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFlagEditsSince(BaseTest):
    @parameterized.expand(
        [
            ("person", True, False, None, False, FlagEditAuthor.PERSON),
            ("agent", True, False, "agent", False, FlagEditAuthor.AGENT),
            ("scheduled_change", True, False, "scheduled_change", False, FlagEditAuthor.SCHEDULED_CHANGE),
            ("system", False, True, None, False, FlagEditAuthor.SYSTEM),
            ("deleted_user", False, False, None, False, FlagEditAuthor.PERSON),
            ("legacy_row_without_a_user", False, None, None, None, FlagEditAuthor.SYSTEM),
            ("exposure_freeze_by_a_person", True, False, "experiment_exposure_frozen", False, FlagEditAuthor.PERSON),
            ("impersonated", True, False, None, True, FlagEditAuthor.PERSON),
        ]
    )
    def test_author(
        self,
        _name: str,
        has_user: bool,
        is_system: bool | None,
        job_type: str | None,
        was_impersonated: bool | None,
        expected: FlagEditAuthor,
    ) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="authored")
        detail: dict[str, Any] = {
            "changes": [{"type": "FeatureFlag", "action": "changed", "field": "key", "before": "a", "after": "b"}]
        }
        if job_type:
            detail["trigger"] = {"job_type": job_type, "job_id": "1", "payload": {}}
        ActivityLog.objects.create(
            team_id=self.team.id,
            scope="FeatureFlag",
            item_id=str(flag.id),
            activity="updated",
            user=self.user if has_user else None,
            is_system=is_system,
            was_impersonated=was_impersonated,
            detail=detail,
        )

        (edit,) = flag_edits_since(
            team_id=self.team.id, feature_flag_id=flag.id, since=timezone.now() - timedelta(days=1), limit=2
        )

        assert edit.author == expected
        assert edit.user_id == (self.user.id if has_user else None)
        assert edit.was_impersonated == bool(was_impersonated)


class TestServedStringsInEdits(BaseTest):
    def test_reads_only_the_teams_edits(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        for team, variant in ((self.team, "mine"), (other_team, "theirs")):
            ActivityLog.objects.create(
                team_id=team.id,
                scope="FeatureFlag",
                item_id="1",
                activity="updated",
                detail={
                    "name": "beta",
                    "changes": [
                        {
                            "type": "FeatureFlag",
                            "action": "changed",
                            "field": "filters",
                            "before": None,
                            "after": {"multivariate": {"variants": [{"key": variant}]}},
                        }
                    ],
                },
            )

        assert served_strings_in_edits(team_id=self.team.id, flag_key="beta", excluded_flag_ids=()) == ["mine"]
