"""Helpers for the metric definitions that experiments and saved metrics store."""

from pydantic import JsonValue

from products.experiments.backend.metric_utils import refresh_team_action_names_in_metric


def refresh_action_names_in_metric(
    metric: dict[str, JsonValue] | None, *, team_id: int, actions_by_id: dict[int, str] | None = None
) -> dict[str, JsonValue] | None:
    """The metric with the current name of each action it references. A deleted action keeps its stored name, and
    `metric` itself never changes. Pass `actions_by_id` (action id to name) to skip the read of the actions, so that a
    caller that renders many metrics reads them once."""
    return refresh_team_action_names_in_metric(metric, team_id, actions_by_id)
