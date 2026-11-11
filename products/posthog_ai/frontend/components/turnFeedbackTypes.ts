import type { RunRef } from '../utils/feedbackEvents'

export interface TurnRatingTarget {
    /** Task id backing the sandbox conversation. Lands in `$ai_session_id`. */
    sessionId: string
    /** Ordinal of the completed turn — the rating's identity, stable across reloads. */
    turnIndex: number
    run: RunRef
    /** The turn's gateway trace id, when the run reported one. Lands in `$ai_trace_id`. */
    traceId?: string
}

export interface TurnFeedbackActionsProps extends TurnRatingTarget {
    turnText: string
    /** When the turn completed, in milliseconds. */
    timestamp?: number
}
