import type { SessionThreadItem } from './session/types'

export interface ChatFeedbackContext {
    sessionId: string
    runtime: 'sandbox' | 'langgraph'
}

export interface ChatFeedbackTarget extends ChatFeedbackContext {
    traceId?: string
    runId?: string
    turnIndex?: number
}

export function chatFeedbackTargets(
    items: readonly SessionThreadItem[],
    context: ChatFeedbackContext | undefined
): Map<string, ChatFeedbackTarget> {
    const targets = new Map<string, ChatFeedbackTarget>()
    if (!context) return targets

    let turnIndex = -1
    let answerId: string | undefined
    for (const item of items) {
        if (item.kind === 'user') {
            turnIndex += 1
            answerId = undefined
        } else if (item.kind === 'assistant' && item.complete && item.text.trim()) {
            answerId = item.id
            if (context.runtime === 'langgraph' && item.traceId) {
                targets.set(item.id, { ...context, traceId: item.traceId })
            }
        } else if (item.kind === 'turn_end') {
            if (context.runtime === 'sandbox' && answerId && turnIndex >= 0) {
                targets.set(answerId, { ...context, turnIndex, traceId: item.traceId, runId: item.runId })
            }
            answerId = undefined
        }
    }
    return targets
}

export function chatFeedbackKey(scope: string, target: ChatFeedbackTarget): string {
    return `${scope}|${target.runtime}|${target.traceId ?? `${target.sessionId}:turn-${target.turnIndex}`}`
}
