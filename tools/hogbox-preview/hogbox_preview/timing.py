"""Lightweight stage timing for the preview bring-up.

The bring-up (and the deferred frontend swap) is a single multi-minute tool
invocation whose STDOUT is a strict ``url=``/``box_id=`` contract the workflow
parses — so progress can't go there. Without any output the CI log shows a
~6-minute void between the step start and ``url=``, which makes it impossible to
tell where the time actually goes. These helpers print
``[hogbox-preview +NNNs] <stage>`` breadcrumbs to STDERR at each major phase
boundary instead: per-stage visibility for free, no new dependency, and the
stdout contract stays untouched.

Elapsed is whole seconds since the tool started, measured with
``time.monotonic()`` so it's immune to wall-clock jumps and needs no formatting
library.
"""

from __future__ import annotations

import sys
import time

# Captured at import (process start) so every stage line is relative to the same
# t0 across both the backend (pen/restore) and the stack (checkout/migrate/...).
_START = time.monotonic()


def stage(message: str) -> None:
    """Emit one ``[hogbox-preview +NNNs] <message>`` line to STDERR."""
    elapsed = int(time.monotonic() - _START)
    sys.stderr.write(f"[hogbox-preview +{elapsed}s] {message}\n")
    sys.stderr.flush()
