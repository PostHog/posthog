"""Presentation imports alerting internals only through the facade."""

from products.metrics.backend import alert_destinations
from products.metrics.backend.facade import alerts as alert_facade


class TestAlertFacadeSurface:
    def test_exposes_destination_constants(self):
        assert alert_facade.METRICS_ALERT_EVENT_IDS
        assert alert_facade.EVENT_KINDS
        assert alert_facade.EVENT_KIND_CONFIG
        assert alert_facade.METRICS_ALERT_SLACK_CONTEXT_ELEMENTS
        assert alert_facade.METRICS_DESTINATION_TYPES

    def test_constants_match_alert_destinations_module(self):
        assert alert_facade.METRICS_ALERT_EVENT_IDS == alert_destinations.METRICS_ALERT_EVENT_IDS
        assert alert_facade.EVENT_KINDS == alert_destinations.EVENT_KINDS
        assert alert_facade.EVENT_KIND_CONFIG == alert_destinations.EVENT_KIND_CONFIG
        assert (
            alert_facade.METRICS_ALERT_SLACK_CONTEXT_ELEMENTS == alert_destinations.METRICS_ALERT_SLACK_CONTEXT_ELEMENTS
        )
        assert alert_facade.METRICS_DESTINATION_TYPES == alert_destinations.METRICS_DESTINATION_TYPES
