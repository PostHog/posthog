"""Validation for experiment retention metric configurations."""

from posthog.schema import ExperimentExposureNode, ExperimentRetentionMetric, StartHandling


def retention_metric_error(metric: ExperimentRetentionMetric) -> str | None:
    """Returns an error message when the retention metric configuration is invalid, else None.

    The query engine ignores the conversion window and start handling for an
    exposure-anchored start, so accepting them would store settings that never apply.
    """
    if not isinstance(metric.start_event, ExperimentExposureNode):
        return None

    if metric.conversion_window is not None or metric.conversion_window_unit is not None:
        return (
            "a conversion window cannot be combined with an experiment exposure start. "
            "Retention already anchors on each user's first exposure."
        )

    if metric.start_handling == StartHandling.LAST_SEEN:
        return (
            "start_handling 'last_seen' cannot be combined with an experiment exposure start. "
            "Retention always anchors on each user's first exposure."
        )

    return None
