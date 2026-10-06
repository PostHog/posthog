from posthog.test.base import BaseTest

from products.review_hog.backend.models import ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact, parse_artefact_content
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FULL, reviewhog_version_for_mode
from products.review_hog.backend.reviewer.fingerprint import ReviewHogMarker, record_turn_marker
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.persistence import upsert_review_report
from products.review_hog.backend.reviewer.skill_loader import REVIEW_HOG_VALIDATION_SKILL_NAME
from products.review_hog.backend.temporal.activities import _sync_review_skills
from products.skills.backend.api.skill_services import publish_skill_version
from products.skills.backend.models.skills import LLMSkill


class TestRecordTurnMarker(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        _sync_review_skills(self.team.id)
        self.report_id = upsert_review_report(
            team_id=self.team.id,
            repository="o/r",
            pr_url="https://github.com/o/r/pull/7",
            pr_metadata=PRMetadata(
                number=7,
                title="t",
                state="open",
                draft=False,
                created_at="",
                updated_at="",
                author="octocat",
                base_branch="main",
                head_branch="feat",
                head_sha="sha1",
                commits=1,
                additions=1,
                deletions=0,
                changed_files=1,
            ),
        )

    def _record(self, run_index: int) -> ReviewHogMarker:
        return record_turn_marker(
            team_id=self.team.id,
            report_id=self.report_id,
            head_sha="sha1",
            run_index=run_index,
            acting_user_id=self.user.id,
            review_mode=REVIEW_MODE_FULL,
            flash_reasoning_effort="medium",
        )

    def _publish_validation_body(self, body: str, base_version: int) -> None:
        publish_skill_version(
            self.team, user=self.user, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME, body=body, base_version=base_version
        )

    def test_a_team_skill_edit_changes_the_fingerprint_and_a_revert_restores_it(self) -> None:
        original = self._record(run_index=1)
        canonical_body = LLMSkill.objects.get(
            team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, is_latest=True
        ).body

        self._publish_validation_body("only flag issues that block the merge", base_version=1)
        edited = self._record(run_index=2)
        self._publish_validation_body(canonical_body, base_version=2)
        reverted = self._record(run_index=3)

        assert original.version == reviewhog_version_for_mode(REVIEW_MODE_FULL)
        assert edited.fingerprint != original.fingerprint
        # The hash covers skill content, not version numbers, so equal skills slice together.
        assert reverted.fingerprint == original.fingerprint

        rows = ReviewReportArtefact.objects.for_team(self.team.id).filter(
            report_id=self.report_id, type=ReviewReportArtefact.ArtefactType.TURN_MARKER
        )
        stored = [parse_artefact_content(row.type, row.content) for row in rows.order_by("created_at")]
        assert all(isinstance(content, TurnMarkerArtefact) for content in stored)
        assert [(c.run_index, c.reviewhog_fingerprint) for c in stored if isinstance(c, TurnMarkerArtefact)] == [
            (1, original.fingerprint),
            (2, edited.fingerprint),
            (3, reverted.fingerprint),
        ]
