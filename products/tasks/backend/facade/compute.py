"""
Facade re-exports for named sandbox sizes.

A size is a fixed vCPU and memory shape that a caller selects for a run. Kept apart from
``facade/sandbox.py`` so that a product that only validates a size does not import the
sandbox providers.
"""

from products.tasks.backend.logic.services.sandbox_config import (
    DEFAULT_SANDBOX_SIZE,
    SANDBOX_SIZE_SHAPES,
    SandboxSize,
    parse_sandbox_size,
)

__all__ = [
    "DEFAULT_SANDBOX_SIZE",
    "SANDBOX_SIZE_SHAPES",
    "SandboxSize",
    "parse_sandbox_size",
]
