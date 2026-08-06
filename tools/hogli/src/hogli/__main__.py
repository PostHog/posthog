"""Command-line entry point for Hogli."""

from __future__ import annotations

# Route through cli.main (not cli directly) so `python -m hogli` marks itself
# as the process entrypoint, matching the `hogli` console script.
from .cli import main

if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
