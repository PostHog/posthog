from dataclasses import replace

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team, User

from products.tasks.backend.facade.profiles import DrivePolicy, Read, get_task_profile
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


VISIBLE_PROFILE = replace(get_task_profile("business_knowledge"), key="test.visibility", api_visible=True)


class TestVisibilityFollowsOriginProfiles(BaseTest):
    @parameterized.expand(
        [
            ("read_kept_without_profile", Task, task_visibility_q, Task.OriginProduct.EXPERIMENTS, None, True),
            (
                "read_dropped_by_creator_profile",
                Task,
                task_visibility_q,
                Task.OriginProduct.EXPERIMENTS,
                {"read_without_channel": Read.CREATOR},
                False,
            ),
            ("read_absent_without_profile", Task, task_visibility_q, Task.OriginProduct.USER_CREATED, None, False),
            (
                "read_added_by_team_profile",
                Task,
                task_visibility_q,
                Task.OriginProduct.USER_CREATED,
                {"read_without_channel": Read.TEAM},
                True,
            ),
            (
                "run_read_added_by_team_profile",
                TaskRun,
                task_run_visibility_q,
                Task.OriginProduct.USER_CREATED,
                {"read_without_channel": Read.TEAM},
                True,
            ),
            (
                "run_read_dropped_by_creator_profile",
                TaskRun,
                task_run_visibility_q,
                Task.OriginProduct.EXPERIMENTS,
                {"read_without_channel": Read.CREATOR},
                False,
            ),
            ("drive_kept_without_profile", Task, task_control_q, Task.OriginProduct.SIGNAL_REPORT, None, True),
            (
                "drive_dropped_by_owner_profile",
                Task,
                task_control_q,
                Task.OriginProduct.SIGNAL_REPORT,
                {"drive": DrivePolicy.OWNER},
                False,
            ),
            (
                "drive_added_by_audience_profile",
                Task,
                task_control_q,
                Task.OriginProduct.USER_CREATED,
                {"drive": DrivePolicy.AUDIENCE},
                True,
            ),
            (
                "read_hidden_by_private_profile",
                Task,
                task_visibility_q,
                Task.OriginProduct.SIGNAL_REPORT,
                {"read_without_channel": Read.TEAM, "api_visible": False},
                False,
            ),
            (
                "run_hidden_by_private_profile",
                TaskRun,
                task_run_visibility_q,
                Task.OriginProduct.SIGNAL_REPORT,
                {"read_without_channel": Read.TEAM, "api_visible": False},
                False,
            ),
        ]
    )
    def test_unfiled_task_from_another_user_follows_its_origin_profile(
        self, _name, model, visibility_q, origin_product, overrides, expected
    ) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@example.com", None)
        task = Task.objects.create(
            team=self.team, created_by=other_user, title="t", description="d", origin_product=origin_product
        )
        TaskRun.objects.create(team=self.team, task=task)
        profiles = (
            {}
            if overrides is None
            else {VISIBLE_PROFILE.key: replace(VISIBLE_PROFILE, origin_product=origin_product, **overrides)}
        )

        with patch.dict("products.tasks.backend.facade.profiles._profiles", profiles):
            visible = model.objects.filter(team_id=self.team.id).filter(visibility_q(self.user.id, self.team.id))

            assert visible.exists() is expected
