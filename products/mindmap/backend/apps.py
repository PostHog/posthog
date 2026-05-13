"""Django app configuration for mindmap."""

from django.apps import AppConfig


class MindmapConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.mindmap.backend"
    label = "mindmap"
