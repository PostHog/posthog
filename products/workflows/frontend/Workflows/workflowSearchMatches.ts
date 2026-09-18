import { isEmailAction } from './hogflows/steps/types'
import { HogFlow, HogFlowAction } from './hogflows/types'

export type WorkflowStepMatchField = 'Step' | 'Email subject' | 'Email preheader'

export interface WorkflowStepMatch {
    actionId: string
    field: WorkflowStepMatchField
    value: string
}

function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * The same matching the list API applies server-side: a case-insensitive literal match where a space in
 * the search term also matches dashes and underscores. Null when the term is blank.
 */
export function workflowSearchRegex(search: string): RegExp | null {
    const term = search.trim()
    if (!term) {
        return null
    }
    return new RegExp(escapeRegExp(term).replace(/ /g, '[\\s\\-_]*'), 'i')
}

function matchStep(action: HogFlowAction, regex: RegExp): WorkflowStepMatch | null {
    if (regex.test(action.name)) {
        return { actionId: action.id, field: 'Step', value: action.name }
    }
    if (!isEmailAction(action)) {
        return null
    }
    const email = action.config.inputs?.email?.value
    const candidates: [WorkflowStepMatchField, unknown][] = [
        ['Email subject', email?.subject],
        ['Email preheader', email?.preheader],
    ]
    for (const [field, value] of candidates) {
        if (typeof value === 'string' && regex.test(value)) {
            return { actionId: action.id, field, value }
        }
    }
    return null
}

/**
 * The steps that put a workflow in the search results when its own name and description did not.
 * A step staged in the draft is checked only when its live version did not match, so a step
 * appears once with the text the person is most likely looking at.
 */
export function findMatchingWorkflowSteps(workflow: HogFlow, search: string): WorkflowStepMatch[] {
    const regex = workflowSearchRegex(search)
    if (!regex || regex.test(workflow.name) || regex.test(workflow.description ?? '')) {
        return []
    }
    const matches: WorkflowStepMatch[] = []
    const matchedActionIds = new Set<string>()
    for (const action of [...workflow.actions, ...(workflow.draft?.actions ?? [])]) {
        if (matchedActionIds.has(action.id)) {
            continue
        }
        const match = matchStep(action, regex)
        if (match) {
            matchedActionIds.add(action.id)
            matches.push(match)
        }
    }
    return matches
}
