"""Shared test fixtures for hogli_commands extension tests.

These tests do not require Django. Run from the repo root with:
    pytest tools/hogli-commands/hogli_commands/tests/ -p no:django -o 'addopts=' -o 'DJANGO_SETTINGS_MODULE='
"""

import os

# The test_runner suite asserts on exact pytest commands. Prevent the local
# warm-django daemon (if running) from prefixing those commands during tests.
os.environ.setdefault("WARM_DJANGO_DISABLE", "1")
