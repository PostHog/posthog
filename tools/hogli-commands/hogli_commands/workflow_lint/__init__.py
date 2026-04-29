"""Workflow lint package: framework + checks for `.github/workflows/**` policies.

The CLI entrypoint is registered via `hogli_commands.workflow_lint.cli` (side-effect
import from `hogli_commands.commands`). To run from the command line:

    bin/hogli lint:workflows
    bin/hogli lint:workflows --check WF001-job-timeouts
    bin/hogli lint:workflows --list
"""

from __future__ import annotations

# Side-effect import: registers the `lint:workflows` Click command with hogli.
from . import cli  # noqa: F401
