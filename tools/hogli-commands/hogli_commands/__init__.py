"""PostHog-specific hogli commands, loaded lazily by the hogli framework.

Each command module is imported on first invoke via the ``click:`` import
strings in ``hogli.yaml``. Boot-time registrations (prechecks, telemetry
property hooks, post-command hooks) are listed in ``config.boot_modules``.

The framework itself lives in ``tools/hogli/``; this package is discovered
via ``config.commands_dir`` in ``hogli.yaml``.
"""

from __future__ import annotations

import sys

from hogli.manifest import REPO_ROOT

# ``hogli_commands.migrations`` imports from ``migration_utils``, a shared
# module at ``common/migration_utils/``. Put ``common/`` on sys.path regardless
# of entry point (bin/hogli, pytest, direct import) so that transitive import
# resolves. This is the only side effect this package performs at import time.
_COMMON = REPO_ROOT / "common"
if _COMMON.is_dir() and str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))
