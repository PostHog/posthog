"""
Shared enumeration types for statistical analysis.

This module contains enums used by both frequentist and Bayesian methods.
"""

from enum import Enum


class DifferenceType(Enum):
    """Types of difference calculations."""

    RELATIVE = "relative"
    ABSOLUTE = "absolute"
