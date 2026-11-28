from __future__ import annotations

from typing import Any

from products.signals.backend.github_optional import GITHUB_OPTIONAL_ACTIVATION
from products.signals.backend.models import InboxOnboardingSetupMode


def setup_mode(state: dict[str, Any]) -> str | None:
    draft = state.get("draft") or {}
    if not draft:
        # Exposure is reported before a draft exists, so there is no mode to report yet.
        return None
    if draft.get("setup_mode"):
        return draft["setup_mode"]
    # A draft without setup_mode came from quick setup when it is a pilot draft, and from the guided steps otherwise.
    if draft.get("activation_mode") == GITHUB_OPTIONAL_ACTIVATION:
        return InboxOnboardingSetupMode.QUICK
    return InboxOnboardingSetupMode.GUIDED


def is_quick_setup(state: dict[str, Any]) -> bool:
    return setup_mode(state) == InboxOnboardingSetupMode.QUICK
