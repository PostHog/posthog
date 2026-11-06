from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.workflow_proposal import WorkflowProposal


class TestWorkflowProposalSourceFence(BaseTest):
    def setUp(self):
        super().setUp()
        self.flow = HogFlow.objects.create(team=self.team, name="Fenced flow")

    def _file(self, source_id: str | None) -> WorkflowProposal:
        return WorkflowProposal.objects.for_team(self.team.pk).create(
            team=self.team,
            hog_flow=self.flow,
            title="Shorten the subject",
            rationale="Opens are low.",
            content={"exit_condition": "exit_only_at_end"},
            base_version=1,
            source_id=source_id,
        )

    def test_a_named_source_is_filed_once_per_workflow(self):
        self._file("run:1:finding:1")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self._file("run:1:finding:1")

    def test_unnamed_sources_do_not_collide(self):
        for source_id in ("", "", None, None):
            self._file(source_id)
        assert WorkflowProposal.objects.for_team(self.team.pk).filter(hog_flow=self.flow).count() == 4
