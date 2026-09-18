"""Distributed ownership: owners.yaml matcher, schema, resolver, and CLI."""

from .census import TeamTestCensus, census, first_team_owner, runner_for_path
from .codeowners import CodeownersProjection, owner_handle, package_dirs_from, project, spellings
from .matcher import compile_pattern, path_matches_pattern
from .resolver import DiskSource, OwnershipSource, OwnersResolver, Resolution

__all__ = [
    "CodeownersProjection",
    "DiskSource",
    "OwnersResolver",
    "OwnershipSource",
    "Resolution",
    "TeamTestCensus",
    "census",
    "compile_pattern",
    "first_team_owner",
    "owner_handle",
    "package_dirs_from",
    "path_matches_pattern",
    "project",
    "runner_for_path",
    "spellings",
]
