from .publish_workflow import PublishWorkflow, publish_docs_pull_request_activity, settle_publication_activity

WORKFLOWS = [PublishWorkflow]
ACTIVITIES = [publish_docs_pull_request_activity, settle_publication_activity]
