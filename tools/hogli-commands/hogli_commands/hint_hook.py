"""Post-command hint hook.

Prints a contextual tip after successful commands.
"""

from __future__ import annotations

from hogli.hooks import register_post_command_hook

from hogli_commands import hints


def _show_hints_post_command(command: str | None, exit_code: int) -> None:
    if exit_code != 0:
        return
    hints.maybe_show_hint(command)


register_post_command_hook(_show_hints_post_command)
