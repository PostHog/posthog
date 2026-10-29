import { describe, expect, it, vi } from 'vitest'

import { buildToolCallProperties, trackCliToolCall } from '@/cli/tool-call-properties'
import { AnalyticsEvent } from '@/lib/posthog/analytics'
import type { ExecInnerCallProperties } from '@/tools/exec'

describe('trackCliToolCall', () => {
    const properties: ExecInnerCallProperties = { duration_ms: 42, success: true, output_format: 'text' }

    it.each(
        [
            'scout-trial-create',
            'scout-trial-get',
            'scout-trial-start',
            'scout-trial-report',
            'scout-trial-list',
            'scout-trial-resume',
            'scout-trial-archive',
            'scout-trial-setup',
            'scout-rubric-generate',
            'scout-rubric-get',
            'scout-rubric-save',
        ].flatMap((toolName) => [false, true].map((success) => ({ toolName, success })))
    )('drops $toolName calls with success=$success, as the hosted server does', ({ toolName, success }) => {
        const trackEvent = vi.fn(async () => {})
        trackCliToolCall({ trackEvent }, toolName, { ...properties, success })
        expect(trackEvent).not.toHaveBeenCalled()
    })

    it.each([false, true])('records other inner calls as $mcp_tool_call with success=%s', (success) => {
        const trackEvent = vi.fn(async () => {})
        trackCliToolCall({ trackEvent }, 'feature-flag-get-all', { ...properties, success })
        expect(trackEvent).toHaveBeenCalledExactlyOnceWith(
            AnalyticsEvent.MCP_TOOL_CALL,
            buildToolCallProperties('feature-flag-get-all', { ...properties, success })
        )
    })
})
