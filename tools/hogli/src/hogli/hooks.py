"""Extension hooks for the hogli CLI framework.

Extensions register hooks here to add custom behavior without modifying
the framework itself. Import from this module (not cli.py) to avoid
circular imports during dynamic command loading.
"""

from __future__ import annotations

from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Precheck registry
# ---------------------------------------------------------------------------


class PrecheckHandler(Protocol):
    def __call__(self, check_config: dict[str, Any], yes: bool) -> bool | None: ...


_precheck_handlers: dict[str, PrecheckHandler] = {}


def register_precheck(check_type: str, handler: PrecheckHandler) -> None:
    """Register a precheck handler for a given type.

    Handler signature: (check_config: dict, yes: bool) -> bool | None
    Return False to abort, True/None to continue.
    """
    _precheck_handlers[check_type] = handler


def get_precheck_handler(check_type: str) -> PrecheckHandler | None:
    return _precheck_handlers.get(check_type)


# ---------------------------------------------------------------------------
# Telemetry property hooks
# ---------------------------------------------------------------------------


class TelemetryPropertyHook(Protocol):
    def __call__(self, command: str | None) -> dict[str, Any]: ...


_telemetry_property_hooks: list[TelemetryPropertyHook] = []


def register_telemetry_properties(hook: TelemetryPropertyHook) -> None:
    """Register a hook that returns extra telemetry properties.

    Hook signature: (command: str | None) -> dict[str, Any]
    """
    _telemetry_property_hooks.append(hook)


def get_telemetry_property_hooks() -> list[TelemetryPropertyHook]:
    return _telemetry_property_hooks


# ---------------------------------------------------------------------------
# Post-command hooks
# ---------------------------------------------------------------------------


class PostCommandHook(Protocol):
    def __call__(self, command: str | None, exit_code: int) -> None: ...


_post_command_hooks: list[PostCommandHook] = []


def register_post_command_hook(hook: PostCommandHook) -> None:
    """Register a hook that runs after every command completes.

    Hook signature: (command: str | None, exit_code: int) -> None
    Exceptions raised by hooks are swallowed so one extension cannot break another.
    """
    _post_command_hooks.append(hook)


def get_post_command_hooks() -> list[PostCommandHook]:
    return _post_command_hooks
