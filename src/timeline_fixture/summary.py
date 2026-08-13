from collections.abc import Iterable


def file_count(paths: Iterable[str]) -> int:
    """Count unique paths for a timeline badge."""
    return len(set(paths))
