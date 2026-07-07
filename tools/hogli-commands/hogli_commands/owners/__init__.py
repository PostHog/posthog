"""Distributed ownership: owners.yaml matcher, schema, resolver, and CLI."""

from .matcher import compile_pattern, path_matches_pattern
from .resolver import OwnersResolver, Resolution

__all__ = [
    "OwnersResolver",
    "Resolution",
    "compile_pattern",
    "path_matches_pattern",
]
