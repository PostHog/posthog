"""Shared constants for the foundry-run-gate workflow stack."""

from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy

# Where a gate run clones the artifact repo inside its sandbox.
GATE_WORKDIR = "/gate/repo"

PROVISION_TIMEOUT = timedelta(minutes=5)
TEARDOWN_TIMEOUT = timedelta(minutes=2)

# Checks are side-effecting (they may run the artifact's own test suite, mutate the working
# tree for mutation testing, etc.) — a crash is reported as a failing check, not silently
# retried and paying for the sandbox work twice.
CHECK_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
DEFAULT_CHECK_TIMEOUT = timedelta(minutes=5)
COVERAGE_CHECK_TIMEOUT = timedelta(minutes=10)

# reviewhog polls a review turn to completion; matches iteration-2's Celery poll cadence
# (~10 minutes total) so the automatic-gate behaviour it replaces doesn't change shape.
REVIEWHOG_POLL_INTERVAL_SECONDS = 15
REVIEWHOG_MAX_POLL_ATTEMPTS = 40
REVIEWHOG_CHECK_TIMEOUT = timedelta(minutes=12)
