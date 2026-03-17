"""
Presentation layer for experiments product.

This module handles HTTP request/response serialization using DRF,
converting between HTTP and facade DTOs.
"""

from .serializers import ExperimentCreateSerializer

__all__ = [
    "ExperimentCreateSerializer",
]
