import { describe, expect, it, vi } from 'vitest'

import { buildToolCallProperties, trackCliToolCall } from '@/cli/tool-call-properties'
import { AnalyticsEvent } from '@/lib/posthog/analytics'
import type { ExecInnerCallProperties } from '@/tools/exec'

describe('trackCliToolCall', () => {
    const properties: ExecInnerCallProperties = { duration_ms: 42, success: true, output_format: 'text' }

    it.each([
        ['scout-trial-create', true],
        ['scout-trial-get', false],
    ])('drops %s calls with success=%s, as the hosted server does', (toolName, success) => {
        const trackEvent = vi.fn(async () => {})
        trackCliToolCall({ trackEvent }, toolName, { ...properties, success })
        expect(trackEvent).not.toHaveBeenCalled()
    })

    it('records other inner calls as $mcp_tool_call', () => {
        const trackEvent = vi.fn(async () => {})
        trackCliToolCall({ trackEvent }, 'feature-flag-get-all', properties)
        expect(trackEvent).toHaveBeenCalledExactlyOnceWith(
            AnalyticsEvent.MCP_TOOL_CALL,
            buildToolCallProperties('feature-flag-get-all', properties)
        )
    })
})
