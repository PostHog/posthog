"""Product scaffolding and linting."""

# Import _cli to trigger @cli.command registration with hogli's CLI group.
from . import cli as _cli  # noqa: F401

# Public API
from .checks import CHECKS, CheckContext, CheckResult, ProductCheck
from .lint import lint_product
from .scaffold import bootstrap_product

__all__ = [
    "CHECKS",
    "CheckContext",
    "CheckResult",
    "ProductCheck",
    "bootstrap_product",
    "lint_product",
]
