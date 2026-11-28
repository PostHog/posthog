from django.apps import AppConfig


class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.workflows.backend"
    label = "workflows"

    def ready(self) -> None:
        from celery.signals import beat_init  # noqa: PLC0415

        from products.workflows.backend.services.inbound_email.schedule import (  # noqa: PLC0415
            register_inbound_email_schedules,
        )

        # Only a beat process sends beat_init, so web and worker processes never touch the schedule.
        beat_init.connect(
            register_inbound_email_schedules, weak=False, dispatch_uid="workflows.inbound_email_schedules"
        )
        from products.actions.backend.facade.api import on_action_saved  # noqa: PLC0415
        from products.workflows.backend import receivers  # noqa: F401, PLC0415 — registers signal receivers
        from products.workflows.backend.models.hog_flow.hog_flow import action_saved_for_hog_flows  # noqa: PLC0415

        # Compiled filters embed each action's matcher, so they must be rebuilt when an action is saved.
        on_action_saved(action_saved_for_hog_flows, dispatch_uid="workflows.hog_flows.action_saved")
