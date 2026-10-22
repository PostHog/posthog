from django.apps import AppConfig


class SlackAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.slack_app.backend"
    label = "slack_app"

    def ready(self) -> None:
        # Import to register Django signal receivers (e.g. cache invalidation on Integration changes)
        import products.slack_app.backend.signals  # noqa: F401
        from products.slack_app.backend import task_profiles  # noqa: PLC0415
        from products.tasks.backend.facade.profiles import register_task_profiles  # noqa: PLC0415

        register_task_profiles(task_profiles.PROFILES)
