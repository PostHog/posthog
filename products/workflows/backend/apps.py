from django.apps import AppConfig


class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.workflows.backend"
    label = "workflows"

    def ready(self) -> None:
        # Registers HogFlow as an entity dependency source once the model registry is populated.
        # Kept in its own light module so django.setup() does not pull the API module in.
        from products.workflows.backend import entity_dependencies  # noqa: F401, PLC0415
