/**
 * The agent-feedback handler enumerates schema fields by hand when it builds the
 * `mcp feedback submitted` analytics payload, so a field added to
 * `FeedbackSubmitSchema` can silently never reach the event downstream consumers
 * aggregate on. This pins the scout-feedback fields (skill name / version /
 * category) — the join keys for per-skill fleet-wide aggregation — to the
 * `feedback_scout_*` event properties.
 */
import { describe, expect, it, vi } from 'vitest'

import { submitFeedbackHandler } from '@/tools/feedback/submit'
import type { Context } from '@/tools/types'

describe('agent-feedback submit handler', () => {
    it('forwards scout feedback fields into the analytics event', async () => {
        const trackEvent = vi.fn().mockResolvedValue(undefined)
        const context = { trackEvent } as unknown as Context

        const result = await submitFeedbackHandler(context, {
            summary: 'discriminator misfires on young projects',
            feedback_type: 'scout',
            sentiment: 'neutral',
            scout_skill_name: 'signals-scout-web-analytics',
            scout_skill_version: 7,
            scout_category: 'discriminator_gap',
            suggested_improvement: 'gate the baseline comparison on >=7 days of history',
        })

        expect(trackEvent).toHaveBeenCalledTimes(1)
        const [event, properties] = trackEvent.mock.calls[0]
        expect(event).toBe('mcp feedback submitted')
        expect(properties).toMatchObject({
            feedback_type: 'scout',
            feedback_scout_skill_name: 'signals-scout-web-analytics',
            feedback_scout_skill_version: 7,
            feedback_scout_category: 'discriminator_gap',
        })
        expect(result.received).toBe(true)
    })
})
