"""Agent runs that another product asked Self-driving to make for one of its records.

A product names an entity by its key, and Self-driving keeps two kinds of rows for it: one row per
pass of an agent over the entity, and one row per report that a pass opened or matched. The product
stores neither. It reads both through `get_attached` when it shows the entity.
"""

from products.signals.backend.agent_run_links import (
    detach_entity as detach_entity,
    get_attached as get_attached,
    linked_entities as linked_entities,
)
from products.signals.backend.agent_run_types import (
    AgentEntity as AgentEntity,
    AgentEntityContent as AgentEntityContent,
    AgentRunOutcome as AgentRunOutcome,
    AgentRunResult as AgentRunResult,
    Attached as Attached,
    AttachedReport as AttachedReport,
    AttachedRun as AttachedRun,
    ImplementationState as ImplementationState,
    ReportImplementation as ReportImplementation,
)
