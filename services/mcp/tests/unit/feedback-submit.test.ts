/**
 * The agent-feedback handler enumerates schema fields by hand when it builds the
 * `mcp feedback submitted` analytics payload, so a field added to
 * `FeedbackSubmitSchema` can silently never reach the event downstream consumers
 * aggregate on. This pins the scout-feedback fields (skill name / version /
 * category) — the join keys for per-skill fleet-wide aggregation — to the
 * `feedback_scout_*` event properties.
 */
import { describe, expect, it, vi } from 'vitest'

import { FeedbackSubmitSchema } from '@/schema/tool-inputs'
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
        expect(trackEvent).toHaveBeenCalledWith(
            'mcp feedback submitted',
            expect.objectContaining({
                feedback_type: 'scout',
                feedback_scout_skill_name: 'signals-scout-web-analytics',
                feedback_scout_skill_version: 7,
                feedback_scout_category: 'discriminator_gap',
            })
        )
        expect(result.received).toBe(true)
    })

    it.each([
        ['scout_skill_name', { scout_skill_version: 7, scout_category: 'discriminator_gap' }],
        ['scout_skill_version', { scout_skill_name: 'signals-scout-web-analytics', scout_category: 'other' }],
        ['scout_category', { scout_skill_name: 'signals-scout-web-analytics', scout_skill_version: 7 }],
    ])('rejects scout feedback missing %s', (_missing, scoutFields) => {
        const result = FeedbackSubmitSchema.safeParse({
            summary: 'discriminator misfires on young projects',
            feedback_type: 'scout',
            sentiment: 'neutral',
            ...scoutFields,
        })
        expect(result.success).toBe(false)
    })

    it('accepts non-scout feedback without scout fields', () => {
        const result = FeedbackSubmitSchema.safeParse({
            summary: 'the SQL editor autocomplete is excellent',
            feedback_type: 'product',
            sentiment: 'positive',
        })
        expect(result.success).toBe(true)
    })
})
