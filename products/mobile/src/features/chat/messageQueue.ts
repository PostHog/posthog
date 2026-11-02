import type { PendingAttachment } from './attachments/types'
import type { SessionPhase } from './session/types'

export interface QueuedMessage {
    id: string
    text: string
    /** The composer's files when the message was queued. They go with it, as on the web. */
    attachments: PendingAttachment[]
}

/**
 * Why a queue waits on the person instead of the agent. `cancelled` follows a Stop; `unconfirmed` follows a failed
 * delivery, which may still have reached the agent.
 */
export type QueueHold = 'cancelled' | 'unconfirmed'

export interface QueueState {
    rows: QueuedMessage[]
    hold: QueueHold | null
}

export type QueueAction =
    | { type: 'enqueue'; id: string; text: string; attachments: PendingAttachment[] }
    | { type: 'remove'; id: string }
    | { type: 'clear' }
    | { type: 'restore'; rows: QueuedMessage[] }
    | { type: 'hold'; reason: QueueHold }
    | { type: 'release' }

export const EMPTY_QUEUE: QueueState = { rows: [], hold: null }

let lastId = 0

export const queueActions = {
    enqueue: (text: string, attachments: readonly PendingAttachment[] = []): QueueAction => ({
        type: 'enqueue',
        id: `queued-${++lastId}`,
        text,
        attachments: [...attachments],
    }),
    remove: (id: string): QueueAction => ({ type: 'remove', id }),
    clear: (): QueueAction => ({ type: 'clear' }),
    restore: (rows: QueuedMessage[]): QueueAction => ({ type: 'restore', rows }),
    hold: (reason: QueueHold): QueueAction => ({ type: 'hold', reason }),
    release: (): QueueAction => ({ type: 'release' }),
}

export function queueReducer(state: QueueState, action: QueueAction): QueueState {
    switch (action.type) {
        case 'enqueue':
            return {
                rows: [...state.rows, { id: action.id, text: action.text, attachments: action.attachments }],
                // A new message is an explicit "send this", so it lifts a Stop's hold. An `unconfirmed` hold stays,
                // because the failed send may have reached the agent and only Send now should repeat it.
                hold: state.hold === 'cancelled' ? null : state.hold,
            }
        case 'remove': {
            const rows = state.rows.filter((row) => row.id !== action.id)
            return { rows, hold: rows.length > 0 ? state.hold : null }
        }
        case 'clear':
            return EMPTY_QUEUE
        case 'restore':
            // The rows a failed send took go back in front of rows queued since, so the send order holds.
            return { rows: [...action.rows, ...state.rows], hold: 'unconfirmed' }
        case 'hold':
            return state.rows.length > 0 ? { ...state, hold: action.reason } : state
        case 'release':
            return state.hold === null ? state : { ...state, hold: null }
    }
}

/** The queued rows go out as one message, so follow-ups never fan out into separate turns. */
export function joinQueue(rows: QueuedMessage[]): string {
    return rows.map((row) => row.text).join('\n\n')
}

/** The files of the joined message, in queue order. The 10-file cap is per composer message, so a join can carry more. */
export function joinQueueAttachments(rows: QueuedMessage[]): PendingAttachment[] {
    return rows.flatMap((row) => row.attachments)
}

export interface SendGate {
    phase: SessionPhase
    /** A send, an answer or a queue delivery is in flight. */
    sending: boolean
    decisionPending: boolean
}

/** A message waits in the queue while anything could make it overtake or interrupt what is already going on. */
export function shouldQueue(gate: SendGate, queue: QueueState): boolean {
    return gate.phase !== 'idle' || gate.sending || gate.decisionPending || queue.rows.length > 0
}

export function canDrain(gate: SendGate, queue: QueueState): boolean {
    return (
        queue.rows.length > 0 && queue.hold === null && gate.phase === 'idle' && !gate.sending && !gate.decisionPending
    )
}

export interface SendNowGate extends SendGate {
    canSteer: boolean
    stopping: boolean
}

export interface SendNowState {
    pending: boolean
    disabledReason?: string
}

export function sendNowState(gate: SendNowGate): SendNowState {
    if (gate.decisionPending) {
        return { pending: false, disabledReason: 'Answer the agent first' }
    }
    if (gate.sending || gate.stopping) {
        return { pending: true }
    }
    if (gate.phase === 'working' && !gate.canSteer) {
        return { pending: false, disabledReason: 'Wait for the agent to start' }
    }
    return { pending: false }
}
