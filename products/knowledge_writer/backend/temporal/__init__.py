from collections.abc import Callable

from .held_requests_workflow import StartHeldRequestsWorkflow, start_held_requests_activity
from .merge_workflow import MergeCheckWorkflow, run_merge_check_activity, tell_docs_check_waiters_activity
from .publish_workflow import PublishWorkflow, publish_docs_pull_request_activity, settle_publication_activity
from .reconcile_workflow import MergeReconcileWorkflow, reconcile_merged_pull_requests_activity

WORKFLOWS = [PublishWorkflow, MergeCheckWorkflow, MergeReconcileWorkflow, StartHeldRequestsWorkflow]
ACTIVITIES: list[Callable[..., object]] = [
    publish_docs_pull_request_activity,
    settle_publication_activity,
    run_merge_check_activity,
    tell_docs_check_waiters_activity,
    reconcile_merged_pull_requests_activity,
    start_held_requests_activity,
]
