from collections.abc import Callable
from typing import Any

from products.docs_freshness.backend.temporal.activities import check_head, record_verdict, start_landed_check
from products.docs_freshness.backend.temporal.workflow import CheckLandedCommitWorkflow, CheckPullRequestHeadWorkflow

WORKFLOWS = [CheckPullRequestHeadWorkflow, CheckLandedCommitWorkflow]

ACTIVITIES: list[Callable[..., Any]] = [check_head, record_verdict, start_landed_check]
