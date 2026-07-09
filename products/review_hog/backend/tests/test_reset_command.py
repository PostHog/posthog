import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact, ReviewSkillConfig, ReviewUserSettings
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.signals.backend.artefact_attribution import ArtefactAttribution


class TestResetReviewHog(BaseTest):
    def test_refuses_outside_debug(self) -> None:
        # The command wipes every team's rows — it must be impossible to run against a non-DEBUG DB.
        with pytest.raises(CommandError):
            call_command("reset_review_hog", yes=True)

    @override_settings(DEBUG=True)
    def test_wipes_every_review_hog_model(self) -> None:
        # The command IS the clean-slate story: a model left off its wipe list (ReviewUserSettings
        # was) silently survives resets and keeps steering later runs' triggers and publishing.
        report = ReviewReport.objects.for_team(self.team.id).create(
            team_id=self.team.id, repository="o/r", pr_number=1, head_branch="b", base_branch="main"
        )
        ReviewReportArtefact.append_finding(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ReviewIssueFinding(
                issue_key="1-a",
                run_index=1,
                title="t",
                file="f.py",
                lines=[LineRange(start=1)],
                body="b",
                suggestion="s",
                priority=IssuePriority.MUST_FIX,
            ),
            attribution=ArtefactAttribution.system(),
        )
        ReviewSkillConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, skill_name="review-hog-perspective-x", enabled=True
        )
        ReviewUserSettings.objects.for_team(self.team.id).create(team_id=self.team.id, user_id=self.user.id)

        call_command("reset_review_hog", yes=True)

        assert ReviewReport.objects.unscoped().count() == 0
        assert ReviewReportArtefact.objects.unscoped().count() == 0
        assert ReviewSkillConfig.objects.unscoped().count() == 0
        assert ReviewUserSettings.objects.unscoped().count() == 0
