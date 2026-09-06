/**
 * The missing-capabilities feed reads the report text from `$mcp_intent` only, so a
 * handler that captured the description under any other property would keep the feed
 * empty while the tool looked healthy. This pins the property name and the event.
 */
import { describe, expect, it, vi } from 'vitest'

import { MissingCapabilityReportSchema } from '@/schema/tool-inputs'
import { reportMissingCapabilityHandler } from '@/tools/feedback/reportMissingCapability'
import type { Context } from '@/tools/types'

describe('report-missing-capability handler', () => {
    it('captures the description as $mcp_intent on $mcp_missing_capability', async () => {
        const trackEvent = vi.fn().mockResolvedValue(undefined)
        const context = { trackEvent } as unknown as Context

        const result = await reportMissingCapabilityHandler(context, {
            description: 'wanted to list the members of a cohort and there is no tool for it',
        })

        expect(trackEvent).toHaveBeenCalledWith('$mcp_missing_capability', {
            $mcp_intent: 'wanted to list the members of a cohort and there is no tool for it',
        })
        expect(result.received).toBe(true)
    })

    it('still answers the agent when capture fails', async () => {
        const trackEvent = vi.fn().mockRejectedValue(new Error('analytics down'))
        const context = { trackEvent } as unknown as Context

        await expect(
            reportMissingCapabilityHandler(context, { description: 'no way to pause an experiment' })
        ).resolves.toMatchObject({ received: true })
    })

    it('rejects an empty description', () => {
        expect(MissingCapabilityReportSchema.safeParse({ description: '' }).success).toBe(false)
    })
})
