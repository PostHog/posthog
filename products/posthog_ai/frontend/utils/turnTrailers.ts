import type { ThreadItem } from '../types/streamTypes'

/** A completed turn's identity and content, handed to `ThreadView`'s `renderTurnTrailer`. */
export interface TurnTrailer {
    /** 0-based ordinal of the completed turn. Stable across reloads: the stored log keeps every
     * `_posthog/turn_complete`, so the fold re-emits separators in the same order. */
    turnIndex: number
    /** True for the most recently completed turn. */
    isLastTurn: boolean
    /** The turn's assistant text, concatenated across its message bubbles. */
    turnText: string
}

/**
 * Maps each `turn_separator` item id to its turn's ordinal and assistant text. A separator marks
 * the end of a completed turn, so a consumer can render per-turn UI (e.g. feedback actions) at
 * the separator's position without the surface knowing what that UI is.
 */
export function computeTurnTrailers(threadItems: ThreadItem[]): Map<string, TurnTrailer> {
    const trailers = new Map<string, TurnTrailer>()
    let turnIndex = 0
    let textParts: string[] = []
    let lastSeparatorId: string | null = null
    for (const item of threadItems) {
        if (item.type === 'assistant_message' && item.text) {
            textParts.push(item.text)
        } else if (item.type === 'human_message') {
            // A crashed turn never emits its separator; its text must not leak into the next turn.
            textParts = []
        } else if (item.type === 'turn_separator') {
            trailers.set(item.id, { turnIndex, isLastTurn: false, turnText: textParts.join('\n\n') })
            lastSeparatorId = item.id
            turnIndex += 1
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
