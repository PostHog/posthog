from __future__ import annotations

from typing import Any

from products.signals.backend.github_optional import GITHUB_OPTIONAL_ACTIVATION
from products.signals.backend.models import InboxOnboardingSetupMode


def setup_mode(state: dict[str, Any]) -> str | None:
    draft = state.get("draft") or {}
    if draft.get("activation_mode") == GITHUB_OPTIONAL_ACTIVATION:
        return InboxOnboardingSetupMode.QUICK
    if not draft:
        # Exposure is reported before a draft exists, so there is no mode to report yet.
        return None
    # Drafts saved before setup_mode existed came from the guided steps.
    return draft.get("setup_mode") or InboxOnboardingSetupMode.GUIDED


def is_quick_setup(state: dict[str, Any]) -> bool:
    return setup_mode(state) == InboxOnboardingSetupMode.QUICK
