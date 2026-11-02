from .merge_workflow import MergeCheckWorkflow, run_merge_check_activity
from .publish_workflow import PublishWorkflow, publish_docs_pull_request_activity, settle_publication_activity

WORKFLOWS = [PublishWorkflow, MergeCheckWorkflow]
ACTIVITIES = [publish_docs_pull_request_activity, settle_publication_activity, run_merge_check_activity]
