import { uuid } from 'lib/utils/dom'

import type { MessageAudienceDestination } from './messageAudience'

// pinned: URL search param the broadcast wizard and the workflow editor read the attempt from
export const ATTEMPT_PREFILL_PARAM = 'attempt'

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const shownAttempts = new Map<string, string>()
const savedWorkflowAttempts = new Map<string, string>()

function attemptKey(source: string, destination: MessageAudienceDestination): string {
    return `${destination}:${source}`
}

export function messageAudienceAttempt(
    source: string | undefined,
    destination: MessageAudienceDestination
): string | undefined {
    return source ? shownAttempts.get(attemptKey(source, destination)) : undefined
}

export function startMessageAudienceAttempt(
    source: string,
    destination: MessageAudienceDestination
): { attemptId: string; started: boolean } {
    const existing = messageAudienceAttempt(source, destination)
    if (existing) {
        return { attemptId: existing, started: false }
    }
    const attemptId = uuid()
    shownAttempts.set(attemptKey(source, destination), attemptId)
    return { attemptId, started: true }
}

export function parseAttemptPrefill(raw: unknown): string | undefined {
    return typeof raw === 'string' && UUID_PATTERN.test(raw) ? raw : undefined
}

export function rememberSavedWorkflowAttempt(workflowId: string, attemptId: string): void {
    savedWorkflowAttempts.set(workflowId, attemptId)
}

export function workflowEntryAttempt(editor: { id?: string; entryAttemptId?: string }): string | undefined {
    return editor.entryAttemptId ?? (editor.id ? savedWorkflowAttempts.get(editor.id) : undefined)
}
