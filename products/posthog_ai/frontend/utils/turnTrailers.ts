import type { ThreadItem } from '../types/streamTypes'

/** A completed turn's identity and content, handed to `ThreadView`'s `renderTurnTrailer`. */
export interface TurnTrailer {
    /** 0-based index of the user message this turn answers, the server's turn numbering. A crashed
     * turn has no trailer but still counts, so the indexes of completed turns can skip a number. */
    turnIndex: number
    /** True for the most recently completed turn. */
    isLastTurn: boolean
    /** The turn's assistant text, concatenated across its message bubbles. */
    turnText: string
    /** The turn's gateway trace id — `$ai_trace_id` on its generations and its feedback. */
    traceId?: string
}

/**
 * Maps each `turn_separator` item id to its turn's index and assistant text. A separator marks
 * the end of a completed turn, so a consumer can render per-turn UI (e.g. feedback actions) at
 * the separator's position without the surface knowing what that UI is.
 */
export function computeTurnTrailers(threadItems: ThreadItem[]): Map<string, TurnTrailer> {
    const trailers = new Map<string, TurnTrailer>()
    let turnIndex = -1
    let textParts: string[] = []
    let lastSeparatorId: string | null = null
    for (const item of threadItems) {
        if (item.type === 'assistant_message' && item.text) {
            textParts.push(item.text)
        } else if (item.type === 'human_message') {
            // A crashed turn never emits its separator; its text must not leak into the next turn.
            textParts = []
            turnIndex += 1
        } else if (item.type === 'turn_separator') {
            // A separator with no answer behind it is a duplicate turn-end marker (the history/live
            // seam can leak one); it is not a turn and gets no trailer. Neither is an answer to a
            // hidden prompt before any user message: the server does not number it, and every such
            // turn would share one index.
            if (textParts.length === 0 || turnIndex < 0) {
                textParts = []
                continue
            }
            trailers.set(item.id, {
                turnIndex,
                isLastTurn: false,
                turnText: textParts.join('\n\n'),
                traceId: item.traceId,
            })
            lastSeparatorId = item.id
            textParts = []
        }
    }
    if (lastSeparatorId) {
        const last = trailers.get(lastSeparatorId)
        if (last) {
            trailers.set(lastSeparatorId, { ...last, isLastTurn: true })
        }
    }
    return trailers
}
