import { describe, expect, it } from 'vitest'

import { buildToolResultPayload, markExecPayload, toolResultAnalyticsProperties } from '@/lib/build-tool-result'
import { getDiscoveryHint, isEmptyToolResult } from '@/lib/discovery-hints'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY } from '@/tools/types'

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
})

describe('getDiscoveryHint', () => {
    it('returns the instrumentation hint when a registered query tool comes back empty', () => {
        const hint = getDiscoveryHint({
            toolName: 'query-error-tracking-issues-list',
            handlerResult: { results: [] },
        })

        expect(hint?.kind).toBe('empty_state')
        expect(hint?.text).toContain('instrument-error-tracking')
        expect(hint?.text).toContain('dateRange')
    })

    it('returns the related-capability hint when the same tool has results', () => {
        const hint = getDiscoveryHint({
            toolName: 'query-error-tracking-issues-list',
            handlerResult: { results: [{ id: 'issue-1' }] },
        })

        expect(hint?.kind).toBe('related_capability')
        expect(hint?.text).toContain('authoring-error-tracking-alerts')
        expect(hint?.text).not.toContain('instrument-error-tracking')
    })

    it.each([
        ['query-logs', 'instrument-logs'],
        ['query-session-recordings-list', 'diagnosing-missing-recordings'],
        ['get-llm-total-costs-for-project', 'instrument-llm-analytics'],
    ])('points %s at %s when empty', (toolName, skillName) => {
        expect(getDiscoveryHint({ toolName, handlerResult: { results: [] } })?.text).toContain(skillName)
    })

    it('cross-sells subscriptions and dashboards after insight creation', () => {
        const hint = getDiscoveryHint({ toolName: 'insight-create', handlerResult: { id: 1, short_id: 'abc' } })

        expect(hint?.text).toContain('managing-subscriptions')
        expect(hint?.text).toContain('building-a-dashboard')
    })

    it('returns undefined for unregistered tools, empty or not', () => {
        expect(getDiscoveryHint({ toolName: 'dashboard-get', handlerResult: { results: [] } })).toBeUndefined()
        expect(getDiscoveryHint({ toolName: 'dashboard-get', handlerResult: { id: 1 } })).toBeUndefined()
    })

    it('returns undefined for a registered empty-state tool with results and no cross-sell entry', () => {
        expect(
            getDiscoveryHint({
                toolName: 'query-session-recordings-list',
                handlerResult: { results: [{ session_id: 's1' }] },
            })
        ).toBeUndefined()
    })
})

describe('buildToolResultPayload discovery hint footer', () => {
    it('appends the hint as a footer on the text channel', () => {
        const payload = buildToolResultPayload({
            handlerResult: { results: [], _posthogUrl: 'https://us.posthog.com/project/2/error_tracking' },
            toolName: 'query-error-tracking-issues-list',
            params: {},
        })

        const text = payload.content[0]?.text ?? ''
        expect(text).toContain('instrument-error-tracking')
        // Footer, not preamble: the serialized result still leads.
        expect(text.indexOf('_posthogUrl')).toBeLessThan(text.indexOf('instrument-error-tracking'))
    })

    it('does not fire for tools without a registered hint', () => {
        const payload = buildToolResultPayload({
            handlerResult: { results: [] },
            toolName: 'dashboard-templates-list',
            params: {},
        })

        expect(payload.content[0]?.text).not.toContain('skill')
    })

    it('keeps output_format=json machine-parseable by skipping the footer', () => {
        const payload = buildToolResultPayload({
            handlerResult: { results: [] },
            toolName: 'query-error-tracking-issues-list',
            params: { output_format: 'json' },
        })

        expect(() => JSON.parse(payload.content[0]?.text ?? '')).not.toThrow()
        expect(payload.content[0]?.text).not.toContain('instrument-error-tracking')
    })

    it.each([
        [
            'an empty result with a hint',
            { results: [] },
            {},
            { mcp_discovery_hint: 'empty_state', mcp_result_empty: true },
        ],
        [
            'a populated result with a hint',
            { results: [{ id: 'issue-1' }] },
            {},
            { mcp_discovery_hint: 'related_capability' },
        ],
        [
            'an empty json result, where no footer fires',
            { results: [] },
            { output_format: 'json' },
            { mcp_result_empty: true },
        ],
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

    it('appends the footer after a formatted-results override', () => {
        const payload = buildToolResultPayload({
            handlerResult: {
                results: [],
                [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: 'No issues in the last 7 days.',
            },
            toolName: 'query-error-tracking-issues-list',
            params: {},
        })

        const text = payload.content[0]?.text ?? ''
        expect(text.startsWith('No issues in the last 7 days.')).toBe(true)
        expect(text).toContain('instrument-error-tracking')
    })
})
