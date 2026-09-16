import dataclasses

# Issue names/descriptions are unbounded text; notifications only need a headline,
# and an oversized Temporal payload (~2 MiB cap) would silently skip the alert.
MAX_ISSUE_NAME_LENGTH = 500
MAX_ISSUE_DESCRIPTION_LENGTH = 5000


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


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

    @classmethod
    def build(
        cls,
        *,
        notification_id: str,
        team_id: int,
        issue_id: str,
        event: str,
        issue_name: str | None = None,
        issue_description: str | None = None,
        **fields: object,
    ) -> "AlertDeliveryWorkflowInputs":
        """Bounded inputs: the only constructor producers should use."""
        return cls(
            notification_id=notification_id,
            team_id=team_id,
            issue_id=issue_id,
            event=event,
            issue_name=_truncate(issue_name, MAX_ISSUE_NAME_LENGTH),
            issue_description=_truncate(issue_description, MAX_ISSUE_DESCRIPTION_LENGTH),
            **fields,  # type: ignore[arg-type]
        )


@dataclasses.dataclass(frozen=True)
class AlertDeliveryWorkflowResult:
    deliveries: int = 0
