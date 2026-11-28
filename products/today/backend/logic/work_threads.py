from collections.abc import Iterator

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..facade.contracts import (
    UnknownWorkSource,
    WorkContext,
    WorkLine,
    WorkSource,
    WorkSourceNotAllowed,
    WorkThread,
    WorkThreadInvalid,
)
from .highlight_types import allows
from .work_registry import load_registry


def find_source(name: str) -> WorkSource:
    source = load_registry().sources.get(name)
    if source is None:
        raise UnknownWorkSource(name)
    return source


def get_work_threads(
    *, team: Team, user: User, source_name: str, ref: str | None, scopes: frozenset[str] | None
) -> list[WorkThread]:
    source = find_source(source_name)
    if not allows(UserAccessControl(user=user, team=team), scopes, *source.scopes):
        raise WorkSourceNotAllowed(source.name)
    # The scope makes a producer's team-scoped model queries read only this team, whoever calls the facade.
    with team_scope(team.id), tags_context(product=Product.TODAY, team_id=team.id):
        threads = source.find(WorkContext(team=team, user=user, ref=ref, scopes=scopes))
    validate_threads(source.name, threads)
    return threads


def validate_threads(source_name: str, threads: object) -> None:
    """Raises `WorkThreadInvalid` for threads the frontend cannot draw, so a producer bug fails where it starts."""

    def invalid(problem: str) -> WorkThreadInvalid:
        return WorkThreadInvalid(f"Work source {source_name!r} {problem}")

    if not isinstance(threads, list) or not all(isinstance(thread, WorkThread) for thread in threads):
        raise invalid("must return a list of WorkThread")
    thread_keys: set[str] = set()
    for thread in threads:
        if thread.key in thread_keys:
            raise invalid(f"returned the thread key {thread.key!r} twice")
        thread_keys.add(thread.key)
        line_keys: set[str] = set()
        step_keys: set[str] = set()
        for line in _lines(thread.line):
            if line.key in line_keys:
                raise invalid(f"used the line key {line.key!r} twice in thread {thread.key!r}")
            line_keys.add(line.key)
            if not line.steps:
                raise invalid(f"returned line {line.key!r} of thread {thread.key!r} without steps")
            for position, step in enumerate(line.steps):
                if step.key in step_keys:
                    raise invalid(f"used the step key {step.key!r} twice in thread {thread.key!r}")
                step_keys.add(step.key)
                if step.options and position < len(line.steps) - 1:
                    raise invalid(f"offers options on step {step.key!r}, which is not the last of line {line.key!r}")
                option_keys = [option.key for option in step.options]
                if len(set(option_keys)) < len(option_keys):
                    raise invalid(f"used an option key twice in step {step.key!r} of thread {thread.key!r}")


def _lines(line: WorkLine) -> Iterator[WorkLine]:
    yield line
    for step in line.steps:
        for alongside in step.alongside:
            yield from _lines(alongside)
