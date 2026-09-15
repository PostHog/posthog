from enum import StrEnum


class RootKind(StrEnum):
    FLAG = "flag"
    DIRECTORY = "directory"


class ScoutName(StrEnum):
    FLAGS = "flags"
    EXPERIMENTS = "experiments"
    ARCHAEOLOGY = "archaeology"


class ClusterStatus(StrEnum):
    CANDIDATE = "candidate"
    DEAD = "dead"
    ALIVE = "alive"
    UNDECIDED = "undecided"
    REAPED = "reaped"
    BURIED = "buried"
    DECLINED = "declined"
    VANISHED = "vanished"


class ClusterRank(StrEnum):
    STRONG = "strong"
    WEAK = "weak"


class BlockedReason(StrEnum):
    OVERSIZE = "oversize"


class InventoryStatus(StrEnum):
    ACTIVE = "active"
    IDLE = "idle"


class ArtefactType(StrEnum):
    HIT = "hit"
    VERDICT = "verdict"
    NOTE = "note"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SCOPE_FLAGS = "flags"
SCOPE_EXPERIMENTS = "experiments"
SCOPE_ALL = "all"
NAMED_SCOPES = frozenset({SCOPE_FLAGS, SCOPE_EXPERIMENTS, SCOPE_ALL})
