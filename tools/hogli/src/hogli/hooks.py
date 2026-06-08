"""Extension hooks for the hogli CLI framework.

Extensions register callables that the framework invokes at known points.
Registries are module-level lists/dicts; read them directly when iterating.
Exceptions raised by hooks are swallowed at call sites so one extension
cannot break another.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

PrecheckHandler = Callable[[dict[str, Any], bool], bool | None]
TelemetryPropertyHook = Callable[[str | None], dict[str, Any]]
PostCommandHook = Callable[[str | None, int], None]

precheck_handlers: dict[str, PrecheckHandler] = {}
telemetry_property_hooks: list[TelemetryPropertyHook] = []
post_command_hooks: list[PostCommandHook] = []


def register_precheck(check_type: str, handler: PrecheckHandler) -> None:
    precheck_handlers[check_type] = handler


def register_telemetry_properties(hook: TelemetryPropertyHook) -> None:
    telemetry_property_hooks.append(hook)


def register_post_command_hook(hook: PostCommandHook) -> None:
    post_command_hooks.append(hook)
