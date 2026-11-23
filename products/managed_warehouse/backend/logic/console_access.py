from products.managed_warehouse.backend.presentation.views import is_enabled


def is_console_enabled(organization_id: str) -> bool:
    """Whether the organization has the managed warehouse, so the console may show it."""
    return is_enabled(organization_id)
