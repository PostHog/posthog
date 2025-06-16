# Re-export validation functions from shared module for backward compatibility
from ..shared.utils import (
    validate_statistic_inputs,
    check_sample_size_adequacy,
    validate_test_inputs,
)

# Make these available at module level
__all__ = [
    "validate_statistic_inputs",
    "check_sample_size_adequacy",
    "validate_test_inputs",
]
