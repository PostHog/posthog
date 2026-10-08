import shutil
import tempfile
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team

from products.review_hog.backend.models import ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact, parse_artefact_content
from products.review_hog.backend.reviewer.constants import (
    FLASH_LENSES,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
    reviewhog_version_for_mode,
)
from products.review_hog.backend.reviewer.fingerprint import ReviewHogMarker, record_turn_marker
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.persistence import upsert_review_report
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_PIPELINE, REVIEW_DESIGN_SINGLE_AGENT
from products.review_hog.backend.reviewer.skill_loader import REVIEW_HOG_VALIDATION_SKILL_NAME
from products.review_hog.backend.reviewer.tools.single_agent_review import SINGLE_AGENT_PROMPT_PATH
from products.review_hog.backend.temporal.activities import _sync_review_skills
from products.skills.backend.api.skill_services import publish_skill_version
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile


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

    def _record(
        self,
        run_index: int,
        team_id: int | None = None,
        report_id: str | None = None,
        review_mode: str = REVIEW_MODE_FULL,
        review_design: str = REVIEW_DESIGN_PIPELINE,
    ) -> ReviewHogMarker:
        return record_turn_marker(
            team_id=team_id or self.team.id,
            report_id=report_id or self.report_id,
            head_sha="sha1",
            run_index=run_index,
            acting_user_id=self.user.id,
            review_mode=review_mode,
            flash_reasoning_effort="medium",
            review_design=review_design,
        )

    def _record_single_agent(self, run_index: int) -> ReviewHogMarker:
        return self._record(run_index, review_mode=REVIEW_MODE_FLASH, review_design=REVIEW_DESIGN_SINGLE_AGENT)

    def _edit_single_agent_prompt(self, prompt_file: str) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        edited_dir = Path(directory.name) / "single_agent_review"
        shutil.copytree(SINGLE_AGENT_PROMPT_PATH, edited_dir)
        edited = edited_dir / prompt_file
        edited.write_text(edited.read_text() + "\nFlag missing tests.\n")
        patcher = patch("products.review_hog.backend.reviewer.fingerprint.SINGLE_AGENT_PROMPT_PATH", edited_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    @parameterized.expand(
        [
            ("core",),
            ("lens_priority",),
            *[(Path(lens.prompt_file).stem,) for lens in FLASH_LENSES.values()],
        ]
    )
    def test_a_prompt_file_edit_changes_the_single_agent_fingerprint(self, prompt_name: str) -> None:
        original = self._record_single_agent(run_index=1)
        self._edit_single_agent_prompt(f"{prompt_name}.md")
        changed = self._record_single_agent(run_index=2)

        assert original.version == "reviewhog-flash-2-0"
        assert changed.fingerprint != original.fingerprint

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

    def test_an_archived_skill_sharing_name_and_version_with_the_live_one_is_ignored(self) -> None:
        original = self._record(run_index=1)
        live = LLMSkill.objects.get(team=self.team, name=REVIEW_HOG_VALIDATION_SKILL_NAME, is_latest=True)
        live_files = list(live.files.all())
        LLMSkill.objects.filter(id=live.id).update(deleted=True, body="archived text")
        recreated = LLMSkill.objects.create(
            team=self.team,
            name=live.name,
            description=live.description,
            body=live.body,
            allowed_tools=live.allowed_tools,
            license=live.license,
            compatibility=live.compatibility,
            metadata=live.metadata,
            version=live.version,
            is_latest=True,
        )
        LLMSkillFile.objects.bulk_create(
            [
                LLMSkillFile(skill=recreated, path=f.path, content=f.content, content_type=f.content_type)
                for f in live_files
            ]
        )

        assert self._record(run_index=2).fingerprint == original.fingerprint

    @parameterized.expand(
        [
            ("license", {"license": "MIT"}),
            ("compatibility", {"compatibility": "Needs a git checkout"}),
            ("metadata", {"metadata": {"audience": "backend"}}),
        ]
    )
    def test_a_republish_of_one_delivered_skill_field_changes_the_fingerprint(
        self, _name: str, field: dict[str, Any]
    ) -> None:
        original = self._record(run_index=1)
        publish_skill_version(
            self.team, user=self.user, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME, base_version=1, **field
        )

        assert self._record(run_index=2).fingerprint != original.fingerprint

    def test_a_child_environment_turn_hashes_the_environment_skills(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="staging")
        _sync_review_skills(child.id)
        child_report_id = upsert_review_report(
            team_id=child.id,
            repository="o/r",
            pr_url="https://github.com/o/r/pull/8",
            pr_metadata=PRMetadata(
                number=8,
                title="t",
                state="open",
                draft=False,
                created_at="",
                updated_at="",
                author="octocat",
                base_branch="main",
                head_branch="feat-2",
                head_sha="sha2",
                commits=1,
                additions=1,
                deletions=0,
                changed_files=1,
            ),
        )
        original = self._record(run_index=1, team_id=child.id, report_id=child_report_id)
        publish_skill_version(
            child, user=self.user, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME, body="only blockers", base_version=1
        )

        assert (
            self._record(run_index=2, team_id=child.id, report_id=child_report_id).fingerprint != original.fingerprint
        )
