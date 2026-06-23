from products.pulse.backend.temporal import metrics


class TestPulseMetricsNoOpOutsideContext:
    """Counters must be safe to call outside a Temporal worker (e.g. unit tests)."""

    def test_dispatcher_counters_noop(self):
        # No assertion target — just must not raise when no activity/workflow context exists.
        metrics.increment_dispatch_outcome("eligible", count=3)
        metrics.increment_dispatch_outcome("dispatched")
        metrics.increment_dispatch_outcome("failed")

    def test_scan_counters_noop(self):
        metrics.increment_scan_outcome("delivered")
        metrics.increment_scan_outcome("failed")
        metrics.record_finding_count(5)
