"""
Facade re-exports for tasks exceptions that cross the boundary.

``SandboxProvisionError`` is raised by sandbox provisioning and caught by callers (e.g. the
notebooks API) to surface a typed failure.
"""

from products.tasks.backend.exceptions import SandboxProvisionError

__all__ = ["SandboxProvisionError"]
