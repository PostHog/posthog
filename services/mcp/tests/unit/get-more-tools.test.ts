import { describe, expect, it, vi } from 'vitest'

import { AnalyticsEvent } from '@/lib/posthog/analytics'
import { getMoreToolsHandler } from '@/tools/feedback/getMoreTools'
import type { Context } from '@/tools/types'

describe('get-more-tools handler', () => {
    it('captures a canonical missing-capability event and acknowledges the report', async () => {
        const trackEvent = vi.fn().mockResolvedValue(undefined)
        const context = { trackEvent } as unknown as Context

        const result = await getMoreToolsHandler(context, {
            goal: 'Compare account activity with billing records',
            missing_capability: 'Query the billing provider alongside PostHog events',
            blocked: false,
            attempted_tool: 'execute-sql',
        })

        expect(trackEvent).toHaveBeenCalledTimes(1)
        expect(trackEvent).toHaveBeenCalledWith(AnalyticsEvent.MCP_MISSING_CAPABILITY, {
            $mcp_intent: 'Query the billing provider alongside PostHog events',
            $mcp_intent_source: 'context_parameter',
            $mcp_resource_name: 'get-more-tools',
            $mcp_version: 2,
            missing_capability_attempted_tool: 'execute-sql',
            missing_capability_blocked: false,
            missing_capability_goal: 'Compare account activity with billing records',
        })
        expect(result.content).toEqual([
            {
                type: 'text',
                text: 'Unfortunately, we have shown you the full tool list. We have noted your feedback and will work to improve the tool list in the future.',
            },
        ])
    })
})
