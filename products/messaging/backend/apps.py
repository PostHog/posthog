"""Django app configuration for messaging."""

from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.messaging.backend"
    label = "messaging"

    def ready(self) -> None:
        from posthog.api.file_system.deletion import register_file_system_type  # noqa: PLC0415
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415

        from products.messaging.backend.models.message_template import MessageTemplate  # noqa: PLC0415

        register_mixin_model("message_template", MessageTemplate)
        register_file_system_type("message_template", "messaging", "MessageTemplate")
