from __future__ import annotations

from collections.abc import Callable
from functools import cache

from posthog.products import load_product_modules

type TargetProvider = Callable[[int, set[str]], set[str]]


@cache
def _providers() -> dict[str, TargetProvider]:
    providers: dict[str, TargetProvider] = {}
    for module in load_product_modules("notebook_app_actions"):
        for action, provider in module.TARGET_PROVIDERS.items():
            if action in providers:
                raise ValueError(f"Multiple notebook app target providers registered for {action}.")
            providers[action] = provider
    return providers


def eligible_action_targets(action: str, team_id: int, target_ids: set[str]) -> set[str]:
    provider = _providers().get(action)
    return provider(team_id, target_ids) if provider is not None else set()
