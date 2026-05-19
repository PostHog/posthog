from products.web_analytics.backend.temporal.web_vitals_signal.activities import (
    evaluate_team_regressions,
    evaluate_team_threshold_crossings,
    list_opted_in_web_vitals_teams,
)
from products.web_analytics.backend.temporal.web_vitals_signal.workflows import WebVitalsSignalsWorkflow

WORKFLOWS = [WebVitalsSignalsWorkflow]
ACTIVITIES = [
    list_opted_in_web_vitals_teams,
    evaluate_team_threshold_crossings,
    evaluate_team_regressions,
]
