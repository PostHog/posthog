import { uuid } from 'lib/utils/dom'

import type { MessageAudienceDestination } from './messageAudience'

// pinned: URL search param the broadcast wizard and the workflow editor read the attempt from
export const ATTEMPT_PREFILL_PARAM = 'attempt'

// pinned: sessionStorage key, so renaming it drops the attempts of workflows saved earlier in the tab
const SAVED_ATTEMPTS_STORAGE_KEY = 'message-audience-saved-attempts'

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const shownAttempts = new Map<string, string>()
const savedAttemptsInTab = new Map<string, string>()

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

function readSavedAttempts(): Record<string, string> {
    try {
        const stored = JSON.parse(sessionStorage.getItem(SAVED_ATTEMPTS_STORAGE_KEY) || '{}')
        return stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {}
    } catch {
        return {}
    }
}

export function rememberSavedWorkflowAttempt(workflowId: string, attemptId: string): void {
    savedAttemptsInTab.set(workflowId, attemptId)
    try {
        sessionStorage.setItem(
            SAVED_ATTEMPTS_STORAGE_KEY,
            JSON.stringify({ ...readSavedAttempts(), [workflowId]: attemptId })
        )
    } catch {
        return
    }
}

export function workflowEntryAttempt(editor: { id?: string; entryAttemptId?: string }): string | undefined {
    if (editor.entryAttemptId) {
        return editor.entryAttemptId
    }
    if (!editor.id) {
        return undefined
    }
    return savedAttemptsInTab.get(editor.id) ?? parseAttemptPrefill(readSavedAttempts()[editor.id])
}
