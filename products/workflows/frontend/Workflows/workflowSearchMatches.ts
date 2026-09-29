import { isEmailAction } from './hogflows/steps/types'
import { HogFlow, HogFlowAction } from './hogflows/types'

export type WorkflowStepMatchField = 'Step' | 'Email subject' | 'Email preheader' | 'Email body'

export interface WorkflowStepMatch {
    actionId: string
    field: WorkflowStepMatchField
    value: string
}

const EXCERPT_PADDING = 40

// Mirrors _EMAIL_BODY_TEXT_SQL in the list API (products/workflows/backend/api/hog_flow.py), so the hint
// shows the text the API matched. The tag pattern skips over quoted attribute values, so a '>' inside
// one does not end the tag early and leak the rest of the attribute into the searchable text.
const HTML_STYLE_BLOCK = /<style[^>]*>[\s\S]*?<\/style>/gi
const HTML_SCRIPT_BLOCK = /<script[^>]*>[\s\S]*?<\/script>/gi
const HTML_TAG = /<[^>"']*(?:(?:"[^"]*"|'[^']*')[^>"']*)*>/g

function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** The body as a person reads it: the editor's plain-text export, else the HTML without styles, scripts and tags. */
function emailBodyText(email: Record<string, unknown> | undefined): string | null {
    if (typeof email?.text === 'string' && email.text.trim()) {
        return email.text
    }
    if (typeof email?.html === 'string') {
        return email.html.replace(HTML_STYLE_BLOCK, ' ').replace(HTML_SCRIPT_BLOCK, ' ').replace(HTML_TAG, ' ')
    }
    return null
}

function excerptAround(text: string, regex: RegExp): string | null {
    const collapsed = text.replace(/\s+/g, ' ').trim()
    const match = regex.exec(collapsed)
    if (!match) {
        return null
    }
    const matchEnd = match.index + match[0].length
    let start = Math.max(0, match.index - EXCERPT_PADDING)
    let end = Math.min(collapsed.length, matchEnd + EXCERPT_PADDING)
    // Snap to word boundaries so the excerpt does not open or close mid-word.
    const firstSpace = collapsed.indexOf(' ', start)
    if (start > 0 && firstSpace !== -1 && firstSpace < match.index) {
        start = firstSpace + 1
    }
    const lastSpace = collapsed.lastIndexOf(' ', end)
    if (end < collapsed.length && lastSpace > matchEnd) {
        end = lastSpace
    }
    return `${start > 0 ? '…' : ''}${collapsed.slice(start, end)}${end < collapsed.length ? '…' : ''}`
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
    const email: Record<string, unknown> | undefined = action.config.inputs?.email?.value
    const candidates: [WorkflowStepMatchField, unknown][] = [
        ['Email subject', email?.subject],
        ['Email preheader', email?.preheader],
    ]
    for (const [field, value] of candidates) {
        if (typeof value === 'string' && regex.test(value)) {
            return { actionId: action.id, field, value }
        }
    }
    const body = emailBodyText(email)
    const excerpt = body ? excerptAround(body, regex) : null
    return excerpt ? { actionId: action.id, field: 'Email body', value: excerpt } : null
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
