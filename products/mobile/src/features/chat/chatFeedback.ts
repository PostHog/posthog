import type { SessionAssistantItem, SessionPhase, SessionThreadItem, SessionTurnEndItem } from './session/types'

export interface ChatFeedbackContext {
    sessionId: string
    runtime: 'sandbox' | 'langgraph'
}

export interface ChatFeedbackTarget extends ChatFeedbackContext {
    traceId?: string
    runId?: string
    turnIndex?: number
}

export interface ChatReplyActions {
    feedback?: ChatFeedbackTarget
}

export function chatReplyActions(
    items: readonly SessionThreadItem[],
    context: ChatFeedbackContext | undefined,
    phase: SessionPhase
): Map<string, ChatReplyActions> {
    const actions = new Map<string, ChatReplyActions>()
    let turnIndex = -1
    let answer: SessionAssistantItem | undefined

    const finishReply = (end?: SessionTurnEndItem): void => {
        if (answer?.complete) {
            let feedback: ChatFeedbackTarget | undefined
            if (context?.runtime === 'langgraph' && answer.traceId) {
                feedback = { ...context, traceId: answer.traceId }
            } else if (context?.runtime === 'sandbox' && end && turnIndex >= 0) {
                feedback = { ...context, turnIndex, traceId: end.traceId, runId: end.runId }
            }
            actions.set(answer.id, { feedback })
        }
        answer = undefined
    }

    for (const item of items) {
        if (item.kind === 'user') {
            finishReply()
            turnIndex += 1
        } else if (item.kind === 'assistant' && item.text.trim()) {
            answer = item
        } else if (item.kind === 'turn_end') {
            finishReply(item)
        }
    }
    if (phase === 'idle') {
        finishReply()
    }
    return actions
}

export function chatFeedbackKey(scope: string, target: ChatFeedbackTarget): string {
    return `${scope}|${target.runtime}|${target.traceId ?? `${target.sessionId}:turn-${target.turnIndex}`}`
}
