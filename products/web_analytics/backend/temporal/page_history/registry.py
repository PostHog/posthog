from products.web_analytics.backend.temporal.page_history.activities import (
    claim_capture,
    finish_capture,
    prune_page_history,
    render_capture,
    schedule_page_history,
)
from products.web_analytics.backend.temporal.page_history.workflows import (
    HeatmapPageHistoryCaptureWorkflow,
    HeatmapPageHistoryTickWorkflow,
)

WORKFLOWS = [HeatmapPageHistoryCaptureWorkflow, HeatmapPageHistoryTickWorkflow]
ACTIVITIES = [claim_capture, render_capture, finish_capture, prune_page_history, schedule_page_history]
