"""Alpha feature gate for the cost-controls work (save mode, budget, batch).

These cost modules live in ``src/`` but stay OFF for everyone until a user is in
the alpha: the request path checks ``cost_controls_enabled(get_posthog_flags())``
before applying any save-mode / budget / batch behaviour. This mirrors PostHog's
early-access "alpha" stage + the ``llm-gateway-cost-controls`` feature flag, so
unwired-but-present code can never affect a non-alpha user.
"""

from __future__ import annotations

import os

# Kebab-case flag key. Mirror in the frontend FEATURE_FLAGS enum and register an
# EarlyAccessFeature at the "alpha" stage so users opt in explicitly.
COST_CONTROLS_FLAG = "llm-gateway-cost-controls"


def cost_controls_enabled(flags: dict[str, str] | None = None, *, debug: bool = False) -> bool:
    """True when the alpha flag is on for this request.

    In debug/local mode only, COST_CONTROLS_ENABLED=true acts as a convenience
    override so developers can test without enrolling in the PostHog flag.  The
    env-var path requires ``debug=True`` so it cannot fire in a production process
    (which never sets LLM_GATEWAY_DEBUG=true), preventing a misconfigured
    deployment from globally enabling alpha behaviour for every tenant.
    """
    if debug and os.getenv("COST_CONTROLS_ENABLED", "").strip().lower() == "true":
        return True
    if not flags:
        return False
    return flags.get(COST_CONTROLS_FLAG, "false").strip().lower() == "true"
