from collections.abc import Callable

from .merge_workflow import MergeCheckWorkflow, run_merge_check_activity, tell_docs_check_waiters_activity
from .publish_workflow import (
    PublishWorkflow,
    StartHeldRequestsWorkflow,
    publish_docs_pull_request_activity,
    settle_publication_activity,
    start_held_requests_activity,
)
from .pull_request_workflow import WriterPullRequestWorkflow, settle_pull_request_activity
from .reconcile_workflow import MergeReconcileWorkflow, reconcile_merged_pull_requests_activity

WORKFLOWS = [
    PublishWorkflow,
    MergeCheckWorkflow,
    MergeReconcileWorkflow,
    WriterPullRequestWorkflow,
    StartHeldRequestsWorkflow,
]
ACTIVITIES: list[Callable[..., object]] = [
    publish_docs_pull_request_activity,
    settle_publication_activity,
    run_merge_check_activity,
    tell_docs_check_waiters_activity,
    reconcile_merged_pull_requests_activity,
    settle_pull_request_activity,
    start_held_requests_activity,
]
