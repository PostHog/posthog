from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.tasks.backend.models import Channel, Task, TaskRun
from products.tasks.backend.visibility import task_control_q, task_run_visibility_q, task_visibility_q


class TestVisibilityQueryShape(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{name}_{scope}", model, visibility_q, team_id)
            for name, model, visibility_q in [
                ("visibility", Task, task_visibility_q),
                ("control", Task, task_control_q),
                ("run_visibility", TaskRun, task_run_visibility_q),
            ]
            for scope, team_id in [("team_scoped", 1), ("unscoped", None)]
        ]
    )
    def test_outer_query_does_not_join_channel_tables(self, _name, model, visibility_q, team_id) -> None:
        sql = str(model.objects.filter(team_id=1).filter(visibility_q(7, team_id)).query)
        outer_from = sql.split(" WHERE ", 1)[0]

        assert "posthog_task_channel" not in outer_from
        assert "EXISTS" not in sql


class TestChildEnvironmentVisibility(BaseTest):
    @parameterized.expand([("visibility", task_visibility_q), ("control", task_control_q)])
    def test_creator_sees_child_environment_task_in_root_team_channel(self, _name, visibility_q) -> None:
        env_team = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="env"
        )
        channel = Channel.objects.unscoped().create(
            team=env_team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=self.user
        )
        task = Task.objects.create(
            team=env_team,
            created_by=self.user,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            channel=channel,
        )

        assert channel.team_id == self.team.id
        assert list(Task.objects.filter(team_id=env_team.id).filter(visibility_q(self.user.id, env_team.id))) == [task]
