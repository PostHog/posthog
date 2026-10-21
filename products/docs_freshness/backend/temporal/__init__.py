from collections.abc import Callable
from typing import Any

from products.docs_freshness.backend.temporal.activities import check_head, record_verdict
from products.docs_freshness.backend.temporal.workflow import CheckPullRequestHeadWorkflow

WORKFLOWS = [CheckPullRequestHeadWorkflow]

ACTIVITIES: list[Callable[..., Any]] = [check_head, record_verdict]
