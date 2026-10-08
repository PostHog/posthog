import type { ToolHooks } from '@/tools/tool-hooks'
import { withAgentNote } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'

// Kept in sync with the editor banner in products/workflows/frontend/Workflows/WorkflowSplitSuggestion.tsx.
export const SPLIT_SUGGESTION_STEP_COUNT = 50

function countSteps(result: unknown): number {
    if (!result || typeof result !== 'object') {
        return 0
    }
    const workflow = result as { actions?: unknown; draft?: { actions?: unknown } | null }
    const live = Array.isArray(workflow.actions) ? workflow.actions.length : 0
    // On an active workflow, graph edits stage in the draft, so the draft is the graph the agent is growing.
    const draft = Array.isArray(workflow.draft?.actions) ? workflow.draft.actions.length : 0
    return Math.max(live, draft)
}

export function splitSuggestionNote(stepCount: number): string {
    return (
        `This workflow has ${stepCount} steps. Workflows with more than ${SPLIT_SUGGESTION_STEP_COUNT} steps are slow ` +
        'to open and hard to change in the PostHog editor. Do not add more steps to it. Tell the user, propose ' +
        'splitting it into smaller workflows chained with Capture event steps, and offer to do the split. Follow ' +
        '"Split a large workflow" in the building-workflows skill, and keep the original until the user approves.'
    )
}

function afterResponse(_context: Context, _params: unknown, result: unknown): unknown {
    const stepCount = countSteps(result)
    return stepCount > SPLIT_SUGGESTION_STEP_COUNT ? withAgentNote(result, splitSuggestionNote(stepCount)) : result
}

export default { afterResponse } satisfies ToolHooks<unknown>
