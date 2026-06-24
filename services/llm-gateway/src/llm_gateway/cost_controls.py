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


def cost_controls_enabled(flags: dict[str, str] | None = None) -> bool:
    """True when the alpha flag is on for this request, or COST_CONTROLS_ENABLED=true locally.

    WARNING: COST_CONTROLS_ENABLED is for local development only. Never set it in
    a production deployment — all users of that instance will receive alpha behaviour
    regardless of their PostHog flag enrollment.
    """
    if os.getenv("COST_CONTROLS_ENABLED", "").strip().lower() == "true":
        return True
    if not flags:
        return False
    return flags.get(COST_CONTROLS_FLAG, "false").strip().lower() == "true"
