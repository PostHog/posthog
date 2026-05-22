"""Command-line entry point for Hogli."""

from __future__ import annotations

from .cli import cli


def main() -> None:
    """Execute the Click application."""

    cli()


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
