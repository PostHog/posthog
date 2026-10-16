"""Facade for the logs API's half of keeping both rows of a platform-owned logs alert in step."""

from products.logs.backend.platform_ownership import on_created, on_deleted, on_updated

__all__ = ["on_created", "on_deleted", "on_updated"]
