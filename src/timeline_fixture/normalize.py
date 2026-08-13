"""Small helpers for the commit timeline fixture."""


def normalize_files(files: list[str]) -> list[str]:
    """Return unique paths in display order."""
    return list(dict.fromkeys(files))
