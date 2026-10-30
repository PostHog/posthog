from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.models import Task, TaskRun
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
