from posthog.enums import LabeledStrEnum


# The labels repeat the values because the published OpenAPI enum lists these exact pairs.
class TaskChannelWriteType(LabeledStrEnum):
    PUBLIC = "public", "public"
    PRIVATE = "private", "private"


class AgentCallbackRequestKind(LabeledStrEnum):
    HEARTBEAT = "heartbeat", "heartbeat"
    AWAITING_INPUT = "awaiting_input", "awaiting_input"
    TURN_FAILED = "turn_failed", "turn_failed"
    COMMAND_DISPATCHED = "command_dispatched", "command_dispatched"
    AGENT_ACTIVITY = "agent_activity", "agent_activity"
    BUDGET_STEER = "budget_steer", "budget_steer"
    PROCESS_KILLED = "process_killed", "process_killed"
    RUN_EVENT = "run_event", "run_event"
