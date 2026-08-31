from posthog.test.base import BaseTest

from parameterized import parameterized

from products.web_analytics.backend.content_autopilot.export import ContentAutopilotExportError, export_proposal
from products.web_analytics.backend.models import ContentAutopilotProposal
from products.web_analytics.backend.test.content_autopilot_test_utils import (
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
        ]
    )
    def test_export_returns_markdown_and_marks_proposal_exported(
        self, _name: str, file_path: str, expected_filename: str | None
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
            ("failed validation", False, "# Valid Markdown", "Resolve the failed validation checks"),
            ("missing Markdown", True, "", "Add Markdown to this proposal"),
        ]
    )
    def test_export_rejects_invalid_proposals(
        self, _name: str, validation_passed: bool, markdown: str, expected_error: str
    ) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(
            self.team,
            create_content_autopilot_run(self.team, profile),
            validation_passed=validation_passed,
            markdown=markdown,
        )

        with self.assertRaisesRegex(ContentAutopilotExportError, expected_error):
            export_proposal(team=self.team, proposal_id=str(proposal.id))

        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW)
