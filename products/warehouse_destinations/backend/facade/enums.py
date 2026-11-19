"""Enums that the warehouse destinations contracts use."""

from enum import StrEnum


class WriteMode(StrEnum):
    """How rows go into the target table."""

    APPEND = "append"
    MERGE = "merge"
    REPLACE = "replace"


class TypePolicy(StrEnum):
    """What a destination does when an incoming column type does not match the table."""

    STRICT = "strict"
    PERMISSIVE = "permissive"


class NewColumnPolicy(StrEnum):
    """What a destination does with incoming columns that the table does not have."""

    ADD = "add"
    IGNORE = "ignore"
