from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.web_analytics.backend.content_autopilot.export import ContentAutopilotExportError, export_proposal
from products.web_analytics.backend.models import ContentAutopilotProposal
from products.web_analytics.backend.models.content_autopilot import default_content_autopilot_package
from products.web_analytics.backend.test.content_autopilot_test_utils import (
    UNSET_CONTENT_PACKAGE,
    create_content_autopilot_profile,
    create_content_autopilot_proposal,
    create_content_autopilot_run,
)


class TestContentAutopilotExport(BaseTest):
    @parameterized.expand(
        [
            ("nested path", "content/guides/example.md", "example.md"),
            ("windows path", "content\\guides\\example.md", "example.md"),
            ("empty basename", "/", None),
            ("dot basename", ".", None),
            ("parent basename", "..", None),
            ("oversized basename", f"{'x' * 256}.md", None),
            ("control character", "example\nname.md", None),
            ("non-string path", 42, None),
            ("missing path", None, None),
        ]
    )
    def test_export_returns_markdown_and_marks_proposal_exported(
        self, _name: str, file_path: object, expected_filename: str | None
    ) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(
            self.team,
            create_content_autopilot_run(self.team, profile),
            file_path=file_path,
        )

        exported_proposal = export_proposal(team=self.team, proposal_id=str(proposal.id))

        self.assertEqual(exported_proposal.filename, expected_filename or f"{proposal.id}.md")
        self.assertEqual(exported_proposal.markdown, proposal.proposed_markdown)
        self.assertEqual(exported_proposal.content_package, proposal.content_package)
        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.EXPORTED)

    @parameterized.expand(
        [
            (
                "failed validation",
                False,
                "# Valid Markdown",
                UNSET_CONTENT_PACKAGE,
                "Resolve the failed validation checks",
            ),
            ("missing Markdown", True, "", UNSET_CONTENT_PACKAGE, "Add Markdown to this proposal"),
            ("blank Markdown", True, "   \n  ", UNSET_CONTENT_PACKAGE, "Add Markdown to this proposal"),
            ("list package", True, "# Valid Markdown", ["file_path"], "does not have valid export details"),
            ("string package", True, "# Valid Markdown", "file_path", "does not have valid export details"),
        ]
    )
    def test_export_rejects_invalid_proposals(
        self, _name: str, validation_passed: bool, markdown: str, content_package: object, expected_error: str
    ) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(
            self.team,
            create_content_autopilot_run(self.team, profile),
            validation_passed=validation_passed,
            markdown=markdown,
            content_package=content_package,
        )

        with self.assertRaisesRegex(ContentAutopilotExportError, expected_error):
            export_proposal(team=self.team, proposal_id=str(proposal.id))

        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW)

    def test_export_refuses_a_second_export_of_the_same_proposal(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))

        export_proposal(team=self.team, proposal_id=str(proposal.id))

        with self.assertRaisesRegex(ContentAutopilotExportError, "ready for review can be exported"):
            export_proposal(team=self.team, proposal_id=str(proposal.id))

    def test_export_refuses_a_proposal_belonging_to_another_team(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))
        other_team = Team.objects.create(organization=self.organization, name="Other project")

        with self.assertRaisesRegex(ContentAutopilotExportError, "could not be found"):
            export_proposal(team=other_team, proposal_id=str(proposal.id))

        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW)

    def test_export_falls_back_to_a_safe_filename_for_an_unfilled_package(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = ContentAutopilotProposal.objects.for_team(self.team.id).create(
            team=self.team,
            run=create_content_autopilot_run(self.team, profile),
            proposal_type=ContentAutopilotProposal.ProposalType.NEW_CONTENT,
            lifecycle_status=ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW,
            title="Draft without a generated package",
            validation_report={"passed": True, "checks": []},
            proposed_markdown="# Draft",
        )

        exported_proposal = export_proposal(team=self.team, proposal_id=str(proposal.id))

        self.assertEqual(exported_proposal.content_package, default_content_autopilot_package())
        self.assertEqual(exported_proposal.filename, f"{proposal.id}.md")
