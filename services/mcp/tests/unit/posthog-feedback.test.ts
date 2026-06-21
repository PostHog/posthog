import { describe, expect, it, vi } from 'vitest'

import { AnalyticsEvent } from '@/lib/posthog/analytics'
import submitPostHogFeedback, { submitPostHogFeedbackHandler } from '@/tools/feedback/submitPostHog'
import type { Context } from '@/tools/types'

function createMockContext(trackEvent = vi.fn(async () => {})): Context {
    return { trackEvent } as unknown as Context
}

describe('posthog-feedback', () => {
    it('registers under the posthog-feedback name', () => {
        expect(submitPostHogFeedback().name).toBe('posthog-feedback')
    })

    it('emits a "posthog feedback submitted" event with mapped properties', async () => {
        const trackEvent = vi.fn(async () => {})
        const ctx = createMockContext(trackEvent)

        const result = await submitPostHogFeedbackHandler(ctx, {
            summary: 'session replay player jumps to the wrong timestamp',
            feedback_type: 'bug',
            sentiment: 'negative',
            product_area: 'session replay',
            details: '- clicked the timeline at 0:30\n- player jumped to 0:00',
            suggested_improvement: 'seek to the clicked position',
            user_request: 'watch a recording around a specific moment',
            task_completed: false,
        })

        expect(trackEvent).toHaveBeenCalledWith(AnalyticsEvent.POSTHOG_FEEDBACK_SUBMITTED, {
            feedback_summary: 'session replay player jumps to the wrong timestamp',
            feedback_type: 'bug',
            feedback_sentiment: 'negative',
            feedback_product_area: 'session replay',
            feedback_details: '- clicked the timeline at 0:30\n- player jumped to 0:00',
            feedback_suggested_improvement: 'seek to the clicked position',
            feedback_user_request: 'watch a recording around a specific moment',
            feedback_task_completed: false,
        })
        expect(result).toMatchObject({ received: true, feedback_type: 'bug', sentiment: 'negative' })
    })

    it('accepts positive feedback (unlike agent-feedback)', async () => {
        const ctx = createMockContext()
        const result = await submitPostHogFeedbackHandler(ctx, {
            summary: 'the new funnels UI is much clearer',
            feedback_type: 'praise',
            sentiment: 'positive',
        })
        expect(result.received).toBe(true)
        expect(result.sentiment).toBe('positive')
    })

    it('never throws when analytics tracking fails', async () => {
        const trackEvent = vi.fn(async () => {
            throw new Error('analytics down')
        })
        const ctx = createMockContext(trackEvent)

        await expect(
            submitPostHogFeedbackHandler(ctx, {
                summary: 'wishing for column pinning in the persons table',
                feedback_type: 'feature_request',
                sentiment: 'neutral',
            })
        ).resolves.toMatchObject({ received: true })
    })
})
