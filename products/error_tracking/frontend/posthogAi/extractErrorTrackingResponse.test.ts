import type { ToolCallMessage } from 'products/posthog_ai/frontend/api/types'

import { extractErrorTrackingResponse } from './extractErrorTrackingResponse'

function toolMessage(
    rawOutput: unknown,
    innerInput?: Record<string, unknown>,
    resolvedKey = 'test-tool'
): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey,
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: {},
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
    }
}

describe('extractErrorTrackingResponse', () => {
    it('accepts outputs carrying known search-response fields', () => {
        const response = { status: 'active', search_query: 'TypeError', issues: [] }
        expect(extractErrorTrackingResponse(toolMessage(response))).toBe(response)
    })

    it("rejects one issue's details, which share only the status field", () => {
        const detail = { id: 'issue-1', name: 'TypeError', status: 'active', severity: 'high', impact: {} }
        expect(extractErrorTrackingResponse(toolMessage(detail))).toBeNull()
    })

    it('rejects outputs without any known field', () => {
        expect(extractErrorTrackingResponse(toolMessage({ results: [{ id: 'issue-1' }] }))).toBeNull()
        expect(extractErrorTrackingResponse(toolMessage(undefined))).toBeNull()
    })
})
