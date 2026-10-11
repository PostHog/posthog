"""Binds each command declared in ``schema.py`` to the handler that runs it.

To add a command, declare it in ``schema.py``, write a handler that calls the target product's
facade, then bind the two here. Dispatch applies every check before the handler runs.
"""

from collections.abc import Callable, Mapping
from typing import Any

from posthog.dataclasses import frozen

from .commands import CommandContext, CommandOutcome
from .handlers import handle_loop, handle_qa, handle_review, handle_stamp
from .schema import (
    COMMAND_DECLARATIONS,
    LOOP,
    QA,
    REVIEW,
    STAMP,
    ArgumentError,
    CommandDeclaration,
    help_table,
    parse_arguments,
)


@frozen
class Invocation[A]:
    """A command whose arguments parsed, ready to run once dispatch has the context."""

    spec: "CommandSpec[A]"
    args: A

    def run(self, context: CommandContext) -> CommandOutcome:
        return self.spec.handler(context, self.args)


@frozen
class CommandSpec[A]:
    declaration: CommandDeclaration[A]
    handler: Callable[[CommandContext, A], CommandOutcome]

    def parse(self, raw_argument: str) -> Invocation[A] | ArgumentError:
        args = parse_arguments(self.declaration, raw_argument)
        if isinstance(args, ArgumentError):
            return args
        return Invocation(spec=self, args=args)


def _index(specs: tuple[CommandSpec[Any], ...]) -> Mapping[str, CommandSpec[Any]]:
    """Specs by canonical verb. Raises ValueError unless every declaration has exactly one handler."""
    bound = [spec.declaration.verb for spec in specs]
    declared = [declaration.verb for declaration in COMMAND_DECLARATIONS]
    if sorted(bound) != sorted(declared):
        raise ValueError(f"Bind each declared command to one handler: declared {declared}, bound {bound}")
    return {spec.declaration.verb: spec for spec in specs}


COMMANDS: Mapping[str, CommandSpec[Any]] = _index(
    (
        CommandSpec(declaration=REVIEW, handler=handle_review),
        CommandSpec(declaration=STAMP, handler=handle_stamp),
        CommandSpec(declaration=QA, handler=handle_qa),
        CommandSpec(declaration=LOOP, handler=handle_loop),
    )
)


def help_text() -> str:
    return f"Commands you can use on a pull request:\n\n{help_table()}"
