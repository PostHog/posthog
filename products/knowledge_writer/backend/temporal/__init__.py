from .backstop import MergeBackstopWorkflow, run_merge_check_activity

WORKFLOWS = [MergeBackstopWorkflow]
ACTIVITIES = [run_merge_check_activity]
