"""Lets a product hand its records to a Self-driving agent, and hear back.

The product that owns an entity type registers a loader and its handlers by dotted path, so signals
never imports the product and nothing loads until a run needs it. Self-driving calls the loader at
the start of every pass, so the agent always reads the entity as it is at that time.
"""

from collections.abc import Callable

from django.utils.module_loading import import_string

from posthog.dataclasses import frozen

from products.signals.backend.agent_run_types import AgentEntity, AgentEntityContent, AgentRunResult

# (team_id, entity_id). None means the entity does not exist any more.
EntityLoader = Callable[[int, str], AgentEntityContent | None]
ResultHandler = Callable[[AgentRunResult], None]
# (team_id, entity, report_id)
FixRunEndedHandler = Callable[[int, AgentEntity, str], None]


@frozen
class AgentSource:
    """The dotted paths a product registered for one agent and entity type."""

    load: str
    on_result: str
    on_fix_run_ended: str | None = None


@frozen
class _SourceKey:
    agent: str
    product: str
    type: str


_SOURCES: dict[_SourceKey, AgentSource] = {}


def register_agent_source(
    *,
    agent: str,
    product: str,
    type: str,
    load: str,
    on_result: str,
    on_fix_run_ended: str | None = None,
) -> None:
    """Register how Self-driving reads and answers one entity type, each as a dotted path.

    `load` is an `EntityLoader`. `on_result` is a `ResultHandler` that receives one result per pass.
    `on_fix_run_ended` is a `FixRunEndedHandler` that Self-driving calls when the fix run of a
    report linked to the entity ends.
    """
    _SOURCES[_SourceKey(agent=agent, product=product, type=type)] = AgentSource(
        load=load, on_result=on_result, on_fix_run_ended=on_fix_run_ended
    )


def get_agent_source(*, agent: str, product: str, type: str) -> AgentSource | None:
    return _SOURCES.get(_SourceKey(agent=agent, product=product, type=type))


def load_agent_entity(*, team_id: int, agent: str, entity: AgentEntity) -> AgentEntityContent | None:
    """The entity as its product returns it now. None when it is gone or no product registered it."""
    source = get_agent_source(agent=agent, product=entity.product, type=entity.type)
    if source is None:
        return None
    loader: EntityLoader = import_string(source.load)
    return loader(team_id, entity.id)


def deliver_agent_run_result(result: AgentRunResult) -> None:
    source = get_agent_source(agent=result.agent, product=result.entity.product, type=result.entity.type)
    if source is None:
        return
    handler: ResultHandler = import_string(source.on_result)
    handler(result)


def notify_fix_run_ended(*, team_id: int, agent: str, entity: AgentEntity, report_id: str) -> None:
    source = get_agent_source(agent=agent, product=entity.product, type=entity.type)
    if source is None or source.on_fix_run_ended is None:
        return
    handler: FixRunEndedHandler = import_string(source.on_fix_run_ended)
    handler(team_id, entity, report_id)
