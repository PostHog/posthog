from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.tasks.backend"
    label = "tasks"

    def ready(self):
        # Signal receivers live in their own import-light modules so every
        # process type (celery, temporal, migrate) wires them without pulling
        # the viewset import graph into django.setup().
        from products.tasks.backend import (  # noqa: F401, PLC0415
            activity_logging,
            search_index,
            task_profiles,
            task_run_sync,
            team_deletion,
        )

        task_profiles.register()
        self._register_tag_visibility()

    def _register_tag_visibility(self) -> None:
        from posthog.models.tag_visibility import register_tag_visibility_filter  # noqa: PLC0415

        def _visible_tasks(team_id: int, user_id: int, user_access_control):
            # Task reads apply channel and creator visibility regardless of access control.
            from products.tasks.backend.facade.api import _visible_task_qs  # noqa: PLC0415

            return _visible_task_qs(team_id, user_id, for_list=True)

        register_tag_visibility_filter("tasks.Task", _visible_tasks)
