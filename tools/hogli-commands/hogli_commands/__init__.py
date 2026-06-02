"""PostHog-specific hogli commands, loaded lazily by the hogli framework.

Each command module is imported on first invoke via the ``click:`` import
strings in ``hogli.yaml``. Boot-time registrations (prechecks, telemetry
property hooks, post-command hooks) are listed in ``config.boot_modules``.

The framework itself lives in ``tools/hogli/``; this package is discovered
via ``config.commands_dir`` in ``hogli.yaml``.
"""
