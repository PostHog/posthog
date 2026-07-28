"""
Exported enums for foundry.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic.py, models.py).
"""

from enum import StrEnum


class BetState(StrEnum):
    DRAFTED = "drafted"
    FUNDED = "funded"
    BUILDING = "building"
    GATED = "gated"
    EXPOSED = "exposed"
    ARCHIVED = "archived"


class BetVerdict(StrEnum):
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    ITERATE = "iterate"


class ExecutionMode(StrEnum):
    """external: any orchestrator POSTs events, Foundry is passive (the default).
    managed: Foundry drives the run itself via the foundry-run-bet Temporal workflow."""

    EXTERNAL = "external"
    MANAGED = "managed"


class NodeStatus(StrEnum):
    SPAWNED = "spawned"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BetEventKind(StrEnum):
    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    NODE_SPAWNED = "node.spawned"
    NODE_FINISHED = "node.finished"
    NODE_FAILED = "node.failed"
    ARTIFACT_READY = "artifact.ready"
    GATE_RESULT = "gate.result"
    EXPOSURE_STARTED = "exposure.started"
    EXPOSURE_ADVANCED = "exposure.advanced"
    EXPOSURE_HALTED = "exposure.halted"
    VERDICT_PROPOSED = "verdict.proposed"
    BUDGET_EXCEEDED = "budget.exceeded"
    KNOWLEDGE_PUBLISHED = "knowledge.published"
    NOTE = "note"
    # System-emitted on every state transition; not accepted from external writers.
    STATE_CHANGED = "state.changed"


# Kinds external writers may POST; STATE_CHANGED is reserved for the state machine.
EXTERNAL_EVENT_KINDS: tuple[BetEventKind, ...] = tuple(k for k in BetEventKind if k != BetEventKind.STATE_CHANGED)


class GateCheckType(StrEnum):
    """Declarable check types in ``gate_config.checks``.

    ``protected_paths`` is deliberately absent: it's implicit and always-on whenever
    ``gate_config.protected_paths`` is non-empty, driven by that top-level field rather than
    a declared check (see ``logic/gauntlet.py``)."""

    COMMAND = "command"
    COVERAGE = "coverage"
    MUTATION = "mutation"
    FLAG_GUARD = "flag_guard"
    REVIEWHOG = "reviewhog"


# Synthetic check_type used for the implicit protected-paths check in gate.result's ``checks``
# breakdown — never a valid value for a declared check in gate_config.checks (see GateCheckType).
PROTECTED_PATHS_CHECK_TYPE = "protected_paths"
