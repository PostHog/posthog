from products.stacks.backend.temporal.activities import clean_up_stacks, compute_stack_diff, push_stack_diff
from products.stacks.backend.temporal.workflows import StackCleanupWorkflow, StackDiffWorkflow, StackPushWorkflow

WORKFLOWS = (StackDiffWorkflow, StackPushWorkflow, StackCleanupWorkflow)
ACTIVITIES = (compute_stack_diff, push_stack_diff, clean_up_stacks)
