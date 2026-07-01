import posthog from 'posthog-js'

export type FeedbackRating = 'bad' | 'okay' | 'good' | 'dismissed' | 'implicit_dismiss'
export type FeedbackTriggerType = 'message_interval' | 'random_sample' | 'manual' | 'retry' | 'cancel'

/**
 * Sinks a conversation-level feedback rating (and optional free text) to PostHog telemetry.
 * `sessionId` is the run's telemetry session id (the conversation id when there is one, else the run id).
 */
export function captureFeedback(
    sessionId: string,
    traceId: string | null,
    rating: FeedbackRating,
    triggerType: FeedbackTriggerType,
    feedbackText?: string
): void {
    posthog.capture('$ai_metric', {
        $ai_metric_name: 'feedback',
        $ai_metric_value: rating,
        $ai_session_id: sessionId,
        $ai_trace_id: traceId,
        feedback_trigger_type: triggerType,
    })

    if (feedbackText) {
        posthog.capture('$ai_feedback', {
            $ai_feedback_text: feedbackText,
            $ai_session_id: sessionId,
            $ai_trace_id: traceId,
            ai_product: 'posthog_ai',
        })
    }
}
