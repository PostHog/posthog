from django.apps import AppConfig


class StreamlitAppsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.streamlit_apps.backend"
    label = "streamlit_apps"

    def ready(self) -> None:
        # Apps are written from web requests and from Celery tasks, so the activity-log receiver
        # must connect in every process, not only where the API module loads.
        from products.streamlit_apps.backend import activity_logging  # noqa: F401, PLC0415
