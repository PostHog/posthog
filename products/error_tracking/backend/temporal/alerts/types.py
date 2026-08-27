import dataclasses


@dataclasses.dataclass(frozen=True)
class AlertDeliveryWorkflowInputs:
    notification_id: str
    team_id: int
    issue_id: str
    event: str
    issue_name: str | None = None
    issue_description: str | None = None
    status: str | None = None
    assignee: str | None = None
    actor_email: str | None = None
    # Reference to the triggering exception event, when the transition has one
    # (ingestion-driven transitions). Event properties are fetched by reference
    # inside activities; nothing large crosses the Temporal payload boundary.
    event_uuid: str | None = None
    event_timestamp: str | None = None
    # Small event-specific extras (e.g. spike baseline values); never exception payloads.
    extra: dict[str, str] | None = None


@dataclasses.dataclass(frozen=True)
class AlertDeliveryWorkflowResult:
    deliveries: int = 0
