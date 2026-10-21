from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import TextIO

from posthog.dataclasses import frozen


@frozen
class TerminalStreams:
    input: TextIO
    output: TextIO


@contextmanager
def open_terminal() -> Iterator[TerminalStreams]:
    with ExitStack() as stack:
        if sys.stdin.isatty() and sys.stdout.isatty():
            input = stack.enter_context(os.fdopen(os.dup(sys.stdin.fileno()), "r", encoding="utf-8"))
            output = stack.enter_context(os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8"))
        else:
            input = stack.enter_context(open("/dev/tty", encoding="utf-8"))
            output = stack.enter_context(open("/dev/tty", "w", encoding="utf-8"))
        yield TerminalStreams(input=input, output=output)
