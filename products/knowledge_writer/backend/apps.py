from django.apps import AppConfig


class KnowledgeWriterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.knowledge_writer.backend"
    label = "knowledge_writer"

    def ready(self) -> None:
        from products.knowledge_writer.backend import receivers  # noqa: PLC0415 — needs the app registry

        receivers.connect()
