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
