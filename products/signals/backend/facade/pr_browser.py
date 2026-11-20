from posthog.enums import LabeledStrEnum

from products.engineering_analytics.backend.facade.contracts import PRState as PRState
from products.signals.backend.monitor_pr import InvalidPullRequest as InvalidPullRequest
from products.signals.backend.pr_browser import (
    PROverview as PROverview,
    PRPage as PRPage,
    get_pr_overview as get_pr_overview,
    list_authored_prs as list_authored_prs,
)


class PRBrowserMonitoringFilter(LabeledStrEnum):
    ALL = "all"
    MONITORED = "monitored"
    UNMONITORED = "unmonitored"
