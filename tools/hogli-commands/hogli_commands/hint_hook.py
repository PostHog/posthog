"""Post-command hint hook.

Prints a contextual tip after successful commands. The hints data module is
lazy-imported so this boot module stays cheap.
"""

from __future__ import annotations

from hogli.hooks import register_post_command_hook


def _show_hints_post_command(command: str | None, exit_code: int) -> None:
    if exit_code != 0:
        return
    # Lazy import: hints uses json/datetime/os. Light, but no need to load it
    # for failed commands or for help-only invocations.
    from hogli_commands import hints

    hints.maybe_show_hint(command)


register_post_command_hook(_show_hints_post_command)
