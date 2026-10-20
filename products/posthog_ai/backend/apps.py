from django.apps import AppConfig


class PosthogAiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.posthog_ai.backend"
    label = "posthog_ai"

    def ready(self) -> None:
        # Deferred import: models aren't loadable at module import time, and ready() must stay light.
        from products.posthog_ai.backend import receivers, task_profiles  # noqa: PLC0415
        from products.tasks.backend.facade.profiles import register_task_profiles  # noqa: PLC0415

        register_task_profiles(task_profiles.PROFILES)
        receivers.connect()
