from posthog.test.base import BaseTest
from unittest import mock

from posthog.models import Team

from products.workflows.backend.facade.testing import create_workflow_for_test
from products.workflows.backend.facade.writes import active_workflow_ids, move_workflow_to_draft


class TestMoveWorkflowToDraft(BaseTest):
    def test_moves_an_active_workflow_of_the_given_teams_to_draft_and_tells_the_workers(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        mine, theirs = (
            create_workflow_for_test(team_id=team.pk, status="active").id for team in (self.team, other_team)
        )

        with (
            mock.patch("posthog.plugins.plugin_server_api.publish_message") as publish,
            self.captureOnCommitCallbacks(execute=True),
        ):
            assert move_workflow_to_draft(mine, team_ids=[self.team.pk]) is True
            assert move_workflow_to_draft(mine, team_ids=[self.team.pk]) is False
            assert move_workflow_to_draft(theirs, team_ids=[self.team.pk]) is False

        assert active_workflow_ids([self.team.pk, other_team.pk]) == [theirs]
        publish.assert_called_once_with("reload-hog-flows", {"teamId": self.team.pk, "hogFlowIds": [mine]})
