from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from posthog.models import Team

from products.workflows.backend.facade.contracts import NewWorkflowIdea
from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.workflow_idea import WorkflowIdea
from products.workflows.backend.services.workflow_ideas import create_ideas, list_open_ideas


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

    def test_storing_the_same_idea_twice_from_a_child_environment_keeps_one_row(self):
        child = Team.objects.create(organization=self.organization, name="Staging", parent_team=self.team)
        item = NewWorkflowIdea(
            key="signup:signed_up", title="Welcome", rationale="New users stall.", definition={}, evidence={}
        )

        first = create_ideas(team_id=child.id, items=[item], source="data_suggestions")
        second = create_ideas(team_id=child.id, items=[item], source="data_suggestions")

        assert (len(first), second) == (1, [])
        assert WorkflowIdea.objects.for_team(self.team.pk).filter(key="signup:signed_up").count() == 1

    def test_listing_ideas_without_definitions_leaves_the_stored_build_unread(self):
        item = NewWorkflowIdea(
            key="signup:signed_up", title="Welcome", rationale="", definition={"actions": ["x" * 1000]}, evidence={}
        )
        create_ideas(team_id=self.team.id, items=[item], source="data_suggestions")

        with CaptureQueriesContext(connection) as queries:
            [listed] = list_open_ideas(team_id=self.team.id, source="data_suggestions", with_definition=False)

        assert listed.definition == {}
        assert not any('"definition"' in query["sql"] for query in queries.captured_queries)
        [full] = list_open_ideas(team_id=self.team.id, source="data_suggestions")
        assert full.definition == item.definition
