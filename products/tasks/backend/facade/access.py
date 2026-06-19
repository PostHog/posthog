"""
Facade re-export for the tasks access check.

``has_tasks_access`` gates whether a user may use the tasks/code product. Presentation
imports it from here rather than reaching the internal ``access`` module directly.
"""

from products.tasks.backend.access import has_tasks_access

__all__ = ["has_tasks_access"]
