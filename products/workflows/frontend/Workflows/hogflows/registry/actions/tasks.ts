import { CreateActionType } from '../../hogFlowEditorLogic'
import { registerStandaloneActionNode } from './actionNodeRegistry'

export const AI_TASK_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Create AI task',
    description: 'Start an AI agent task with instructions from this workflow.',
    config: {
        template_id: 'template-posthog-create-task',
        // Pinned rather than relying on the template default: the engine only reads
        // action.config.inputs at execution time, and this value is what turns a 409
        // "task limit reached" reply into a graceful skip instead of a failed step.
        inputs: { non_failure_status_codes: { value: [409] } },
    },
    output_variable: { key: 'task', result_path: null, label: 'Task' },
    // The fixed fields of the step result. Fields the agent returns are added by hand as
    // `output.<name>` mappings, which is also what asks the agent for them.
    getOutputMappingSuggestions: () =>
        Promise.resolve([
            { key: 'task_run_id', result_path: 'run_id', label: 'Run ID' },
            { key: 'task_status', result_path: 'status', label: 'Status' },
            { key: 'task_summary', result_path: 'final_message', label: 'Summary' },
            { key: 'task_pr_urls', result_path: 'pr_urls', label: 'Pull request URLs' },
        ]),
}

registerStandaloneActionNode(AI_TASK_ACTION_NODE)
