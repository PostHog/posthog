from django.apps import AppConfig


class ManagedMigrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.managed_migrations.backend"
    label = "managed_migrations"
