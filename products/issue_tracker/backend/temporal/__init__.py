from .workflows import IssueProcessingWorkflow
from .activities import process_issue_moved_to_todo_activity

WORKFLOWS = [
    IssueProcessingWorkflow,
]

ACTIVITIES = [
    process_issue_moved_to_todo_activity,
]
