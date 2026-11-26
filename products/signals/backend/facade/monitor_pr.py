from products.engineering_analytics.backend.facade.contracts import PRState as PRState
from products.signals.backend.models import SignalReport
from products.signals.backend.monitor_pr import (
    InvalidPullRequest as InvalidPullRequest,
    PRMonitoringLimitExceeded as PRMonitoringLimitExceeded,
    PRMonitoringRequestResult as PRMonitoringRequestResult,
    PRMonitoringUnavailable as PRMonitoringUnavailable,
    PRPage as PRPage,
    list_authored_prs as list_authored_prs,
    request_pr_monitoring as request_pr_monitoring,
)

REPORT_STATUS_CHOICES: tuple[tuple[str, str], ...] = tuple(
    (value, str(label)) for value, label in SignalReport.Status.choices
)
