"""Public interface of the event definitions product."""

from collections.abc import Callable

from products.event_definitions.backend.logic import event_property_purge


def delete_event_properties_for_team(
    team_id: int, should_stop: Callable[[], bool] | None = None, batch_size: int = 10000
) -> bool:
    """Delete the team's event properties in bounded batches. Return False when ``should_stop`` ended it first."""
    return event_property_purge.delete_event_properties_for_team(
        team_id, should_stop=should_stop, batch_size=batch_size
    )
