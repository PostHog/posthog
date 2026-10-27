from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.experiments.backend"
    label = "experiments"

    def ready(self) -> None:
        # Registers activity signal receivers after the app registry is ready.
        import products.experiments.backend.activity_logging  # noqa: F401, PLC0415

        # Approvals runs these actions when a request is approved, and may not import this product,
        # so every process registers them here. They import models, so they wait for app loading.
        from products.approvals.backend.actions.registry import register_action  # noqa: PLC0415
        from products.experiments.backend.approval_actions import LIFECYCLE_ACTIONS  # noqa: PLC0415

        for action_class in LIFECYCLE_ACTIONS:
            register_action(action_class)
