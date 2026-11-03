import { describe, expect, it } from 'vitest'

import { buildToolResultPayload, markExecPayload, toolResultAnalyticsProperties } from '@/lib/build-tool-result'
import { isEmptyToolResult } from '@/lib/empty-tool-result'

describe('isEmptyToolResult', () => {
    it('treats an empty array as empty', () => {
        expect(isEmptyToolResult([])).toBe(true)
    })

    it('treats an empty `results` envelope as empty', () => {
        expect(isEmptyToolResult({ results: [], _posthogUrl: 'https://us.posthog.com/project/2' })).toBe(true)
    })

    it('treats populated results as non-empty', () => {
        expect(isEmptyToolResult([{ id: 1 }])).toBe(false)
        expect(isEmptyToolResult({ results: [{ id: 1 }] })).toBe(false)
    })

    it('treats unknown shapes as non-empty rather than guessing', () => {
        expect(isEmptyToolResult({ id: 123, name: 'My insight' })).toBe(false)
        expect(isEmptyToolResult({ results: {} })).toBe(false)
        expect(isEmptyToolResult('plain string')).toBe(false)
        expect(isEmptyToolResult(null)).toBe(false)
        expect(isEmptyToolResult(undefined)).toBe(false)
    })

    it.each([
        ['logs-context', 'timeline'],
        ['apm-service-health', 'services'],
        ['logs-group-by', 'groups'],
    ])('reads the primary array of %s from `%s`', (toolName, key) => {
        expect(isEmptyToolResult({ [key]: [] }, toolName)).toBe(true)
        expect(isEmptyToolResult({ [key]: [{ id: 1 }] }, toolName)).toBe(false)
    })
})

describe('toolResultAnalyticsProperties', () => {
    it.each([
        ['an empty result', { results: [] }, {}, { mcp_result_empty: true }],
        ['a populated result', { results: [{ id: 'issue-1' }] }, {}, {}],
        ['an empty json result', { results: [] }, { output_format: 'json' }, { mcp_result_empty: true }],
    ])(
        'records %s for the tool-call event, before and after the exec stamp',
        (_label, handlerResult, params, expected) => {
            const payload = buildToolResultPayload({
                handlerResult,
                toolName: 'query-error-tracking-issues-list',
                params,
            })

            expect(toolResultAnalyticsProperties(payload)).toEqual(expected)
            expect(toolResultAnalyticsProperties(markExecPayload(payload))).toEqual(expected)
        }
    )
})
