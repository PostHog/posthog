import posthog from 'posthog-js'

export interface RunRef {
    taskId?: string
    runId?: string
}

/** Shared properties for sandbox-runtime feedback events, so dashboards can split by runtime. */
function feedbackContext(sessionId: string, traceId: string | null, run: RunRef | undefined): Record<string, unknown> {
    return {
        $ai_session_id: sessionId,
        $ai_trace_id: traceId,
        agent_runtime: 'sandbox',
        task_id: run?.taskId ?? null,
        run_id: run?.runId ?? null,
    }
}

export function captureTurnRating(
    sessionId: string,
    traceId: string | null,
    rating: 'good' | 'bad',
    turnIndex: number,
    run?: RunRef
): void {
    posthog.capture('$ai_metric', {
        $ai_metric_name: 'quality',
        $ai_metric_value: rating,
        turn_index: turnIndex,
        ...feedbackContext(sessionId, traceId, run),
    })
}

export function captureTurnFeedbackText(
    sessionId: string,
    traceId: string | null,
    feedbackText: string,
    turnIndex: number,
    run?: RunRef
): void {
    posthog.capture('$ai_feedback', {
        $ai_feedback_text: feedbackText,
        ai_product: 'posthog_ai',
        turn_index: turnIndex,
        ...feedbackContext(sessionId, traceId, run),
    })
}

export type FeedbackPromptRating = 'bad' | 'okay' | 'good' | 'dismissed' | 'implicit_dismiss'
export type FeedbackPromptTrigger = 'message_interval' | 'random_sample' | 'manual' | 'cancel'

/** The periodic prompt's rating (and optional text) — the legacy `captureFeedback` shape plus runtime properties. */
export function capturePromptFeedback(
    sessionId: string,
    traceId: string | null,
    rating: FeedbackPromptRating,
    trigger: FeedbackPromptTrigger,
    turnIndex: number | null,
    run?: RunRef,
    feedbackText?: string
): void {
    posthog.capture('$ai_metric', {
        $ai_metric_name: 'feedback',
        $ai_metric_value: rating,
        feedback_trigger_type: trigger,
        turn_index: turnIndex,
        ...feedbackContext(sessionId, traceId, run),
    })
    if (feedbackText) {
        posthog.capture('$ai_feedback', {
            $ai_feedback_text: feedbackText,
            ai_product: 'posthog_ai',
            turn_index: turnIndex,
            ...feedbackContext(sessionId, traceId, run),
        })
    }
}
