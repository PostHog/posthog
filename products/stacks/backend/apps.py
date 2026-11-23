"""Django app configuration for stacks."""

from django.apps import AppConfig


class StacksConfig(AppConfig):
    name = "products.stacks.backend"
    label = "stacks"
    verbose_name = "Stacks"

    def ready(self) -> None:
        # Registers the configuration system checks and the change request task profile.
        from products.stacks.backend import checks, task_profiles  # noqa: F401, PLC0415

        task_profiles.register()
