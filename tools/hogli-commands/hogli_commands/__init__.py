"""PostHog-specific hogli commands, loaded by the hogli framework.

The hogli framework itself lives in tools/hogli/. This package is discovered
via `config.commands_dir` in hogli.yaml.
"""

from __future__ import annotations

import sys
from pathlib import Path

# `hogli_commands.migrations` imports from `migration_utils`, a shared module at
# `common/migration_utils/`. Put `common/` on sys.path regardless of entry point
# (bin/hogli, pytest, direct import) so that transitive import resolves.
_COMMON = Path(__file__).resolve().parents[3] / "common"
if _COMMON.is_dir() and str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))

from . import commands  # noqa: E402, F401
