"""
Facade re-exports for the sandbox execution surface.

These are behavioral primitives (abstract base class + config/value types + factory
functions), not data — other products construct and drive sandboxes through them. They
cross the boundary as objects, per the wiring pattern. Kept out of ``facade/api.py`` so the
heavy docker/modal dependencies stay off the light data-surface import path.
"""

from products.tasks.backend.logic.services.sandbox import (
    SandboxBase,
    SandboxClass,
    SandboxConfig,
    SandboxResources,
    SandboxStatus,
    SandboxTemplate,
    get_sandbox_class,
    get_sandbox_class_for_backend,
    is_public_sandbox_repo,
)

__all__ = [
    "SandboxBase",
    "SandboxClass",
    "SandboxConfig",
    "SandboxResources",
    "SandboxStatus",
    "SandboxTemplate",
    "get_sandbox_class",
    "get_sandbox_class_for_backend",
    "is_public_sandbox_repo",
]
