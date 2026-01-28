from django.apps import AppConfig


class SlackAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.slack_app.backend"
    label = "slack_app"
