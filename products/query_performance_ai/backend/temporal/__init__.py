from .activities import (
    CreateAutoresearchTaskInput,
    CreateAutoresearchTaskOutput,
    CreatePrWritingTaskInput,
    CreatePrWritingTaskOutput,
    FetchCandidatesInput,
    FetchCandidatesOutput,
    PostSlackSummaryInput,
    WaitForTaskInput,
    WaitForTaskOutput,
    create_autoresearch_task,
    create_pr_writing_task,
    fetch_slow_query_candidates_activity,
    post_slack_summary,
    wait_for_autoresearch_task,
)
from .workflows import (
    AnalyzeAndFixSlowQueryInput,
    AnalyzeAndFixSlowQueryOutput,
    AnalyzeAndFixSlowQueryWorkflow,
    WeeklyAutoresearchInput,
    WeeklyAutoresearchOutput,
    WeeklyAutoresearchWorkflow,
)

WORKFLOWS = [WeeklyAutoresearchWorkflow, AnalyzeAndFixSlowQueryWorkflow]

ACTIVITIES = [
    fetch_slow_query_candidates_activity,
    create_autoresearch_task,
    create_pr_writing_task,
    wait_for_autoresearch_task,
    post_slack_summary,
]

__all__ = [
    "ACTIVITIES",
    "AnalyzeAndFixSlowQueryInput",
    "AnalyzeAndFixSlowQueryOutput",
    "AnalyzeAndFixSlowQueryWorkflow",
    "CreateAutoresearchTaskInput",
    "CreateAutoresearchTaskOutput",
    "CreatePrWritingTaskInput",
    "CreatePrWritingTaskOutput",
    "FetchCandidatesInput",
    "FetchCandidatesOutput",
    "PostSlackSummaryInput",
    "WaitForTaskInput",
    "WaitForTaskOutput",
    "WeeklyAutoresearchInput",
    "WeeklyAutoresearchOutput",
    "WeeklyAutoresearchWorkflow",
    "WORKFLOWS",
    "create_autoresearch_task",
    "create_pr_writing_task",
    "fetch_slow_query_candidates_activity",
    "post_slack_summary",
    "wait_for_autoresearch_task",
]
