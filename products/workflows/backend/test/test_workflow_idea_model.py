from posthog.test.base import BaseTest

from posthog.models import Team

from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.workflow_idea import WorkflowIdea


class TestWorkflowIdeaModel(BaseTest):
    def test_linking_a_workflow_from_another_project_is_refused(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        idea = WorkflowIdea.objects.for_team(self.team.pk).create(
            team=self.team, key="activation:signed_up", title="Welcome", rationale="New users stall.", definition={}
        )
        idea.hog_flow = HogFlow.objects.create(team=other_team, name="Elsewhere")
        with self.assertRaises(ValueError):
            idea.save()
        idea.hog_flow = HogFlow.objects.create(team=self.team, name="Here")
        idea.save()
        assert WorkflowIdea.objects.for_team(self.team.pk).get(id=idea.id).hog_flow_id == idea.hog_flow.id

    def test_a_workflow_in_a_child_environment_can_be_linked_and_saved_again(self):
        child = Team.objects.create(organization=self.organization, name="Staging", parent_team=self.team)
        idea = WorkflowIdea.objects.for_team(self.team.pk).create(
            team=child,
            key="activation:signed_up",
            title="Welcome",
            rationale="New users stall.",
            definition={},
            hog_flow=HogFlow.objects.create(team=child, name="Child flow"),
        )
        assert idea.team_id == self.team.id
        idea.status = WorkflowIdea.Status.ACCEPTED
        idea.save()
