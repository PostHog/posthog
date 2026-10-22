from django.apps import AppConfig


class EndpointsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.endpoints.backend"
    label = "endpoints"
    verbose_name = "Endpoints (product)"

    def ready(self) -> None:
        from products.data_warehouse.backend.facade.api import register_sql_reference_rewrite_handler

        def rewrite_endpoint_references(
            team_id: int, old_name: str, new_name: str, user_access_control: object | None
        ) -> int:
            from products.endpoints.backend.logic.rename import rewrite_endpoint_version_sql_references

            return rewrite_endpoint_version_sql_references(team_id, old_name, new_name, user_access_control)

        register_sql_reference_rewrite_handler("endpoints", rewrite_endpoint_references)
