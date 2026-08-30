from posthog.test.base import BaseTest

from products.web_analytics.backend.content_autopilot.delivery import export_proposal
from products.web_analytics.backend.content_autopilot.lifecycle import ContentAutopilotLifecycleError
from products.web_analytics.backend.models import ContentAutopilotProposal
from products.web_analytics.backend.test.content_autopilot_test_utils import (
    create_content_autopilot_profile,
    create_content_autopilot_proposal,
    create_content_autopilot_run,
)


class TestContentAutopilotDelivery(BaseTest):
    def test_export_returns_markdown_and_records_delivery(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))

        filename, markdown, content_package = export_proposal(proposal=proposal)

        self.assertEqual(filename, "example.md")
        self.assertEqual(markdown, proposal.proposed_markdown)
        self.assertEqual(content_package, proposal.content_package)
        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.EXPORTED)
        self.assertEqual(proposal.delivery_state, ContentAutopilotProposal.DeliveryState.DELIVERED)

    def test_export_rejects_a_proposal_that_failed_blocking_validation(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(
            self.team,
            create_content_autopilot_run(self.team, profile),
            validation_passed=False,
        )

        with self.assertRaises(ContentAutopilotLifecycleError):
            export_proposal(proposal=proposal)

        proposal.refresh_from_db()
        self.assertEqual(proposal.delivery_state, ContentAutopilotProposal.DeliveryState.NOT_DELIVERED)
