from collections.abc import Callable

from django.dispatch import Signal

# Source products prepare follow-up work after a scout files evidence, without starting it.
scout_report_filed = Signal()

_run_guards: dict[str, Callable[[int, str], str | None]] = {}
_contexts: dict[str, Callable[[int, str], str]] = {}


def register_scout_source(
    source: str, *, guard: Callable[[int, str], str | None], context: Callable[[int, str], str]
) -> None:
    _run_guards[source] = guard
    _contexts[source] = context


def scout_source_refusal(source: str, team_id: int, source_id: str) -> str | None:
    guard = _run_guards.get(source)
    return guard(team_id, source_id) if guard else None


def scout_source_context(source: str, team_id: int, source_id: str) -> str:
    context = _contexts.get(source)
    return context(team_id, source_id) if context else ""
