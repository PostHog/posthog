"""
Enumeration types for the frequentist stats module.
"""

from enum import Enum


class DifferenceType(Enum):
    """Types of difference calculations."""

    RELATIVE = "relative"
    ABSOLUTE = "absolute"


class TestType(Enum):
    """Available test types."""

    TWO_SIDED = "two_sided"
