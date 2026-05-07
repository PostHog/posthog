"""Product scaffolding and linting."""

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
