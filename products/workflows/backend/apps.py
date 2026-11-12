from django.apps import AppConfig


class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.workflows.backend"
    label = "workflows"

    def ready(self) -> None:
        from products.actions.backend.facade.api import on_action_saved  # noqa: PLC0415
        from products.workflows.backend import receivers  # noqa: F401, PLC0415 — registers signal receivers
        from products.workflows.backend.models.hog_flow.hog_flow import action_saved_for_hog_flows  # noqa: PLC0415

        # Compiled filters embed each action's matcher, so they must be rebuilt when an action is saved.
        on_action_saved(action_saved_for_hog_flows, dispatch_uid="workflows.hog_flows.action_saved")
