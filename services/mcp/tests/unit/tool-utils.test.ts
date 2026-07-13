import { describe, expect, it } from 'vitest'

import {
    TRACE_MAX_EVENTS,
    TRACE_MAX_FIELD_CHARS,
    TRACE_MAX_TOTAL_HEAVY_CHARS,
    truncateTraceContent,
} from '@/tools/tool-utils'

describe('truncateTraceContent', () => {
    function makeEvent(overrides: Record<string, unknown> = {}): Record<string, unknown> {
        return {
            id: 'evt-1',
            event: '$ai_generation',
            createdAt: '2026-07-01T00:00:00Z',
            properties: {
                $ai_model: 'claude',
                $ai_input_tokens: 10,
                $ai_total_cost_usd: 0.01,
                ...overrides,
            },
        }
    }

    it('leaves a small trace untouched', () => {
        const results = [{ id: 't1', inputState: 'hi', events: [makeEvent({ $ai_input: [{ content: 'short' }] })] }]

        const summary = truncateTraceContent(results)

        expect(summary).toEqual({ truncated: false, omittedEvents: 0 })
        expect((results[0]!.events![0] as any).properties.$ai_input).toEqual([{ content: 'short' }])
    })

    it('truncates an oversized heavy field with an inline marker while preserving metadata', () => {
        const bigInput = [{ content: 'x'.repeat(TRACE_MAX_FIELD_CHARS + 5_000) }]
        const results = [{ id: 't1', events: [makeEvent({ $ai_input: bigInput })] }]

        const summary = truncateTraceContent(results)

        const props = (results[0]!.events![0] as any).properties
        expect(summary.truncated).toBe(true)
        expect(typeof props.$ai_input).toBe('string')
        expect(props.$ai_input).toContain('truncated')
        expect(props.$ai_input.length).toBeLessThanOrEqual(TRACE_MAX_FIELD_CHARS + 200)
        // Lightweight metadata is never touched.
        expect(props.$ai_model).toBe('claude')
        expect(props.$ai_total_cost_usd).toBe(0.01)
    })

    it('caps event count and reports how many were dropped', () => {
        const events = Array.from({ length: TRACE_MAX_EVENTS + 40 }, (_, i) => makeEvent({ $ai_model: `m${i}` }))
        const results = [{ id: 't1', events }]

        const summary = truncateTraceContent(results)

        expect(summary.truncated).toBe(true)
        expect(summary.omittedEvents).toBe(40)
        expect((results[0]!.events as unknown[]).length).toBe(TRACE_MAX_EVENTS)
    })

    it('enforces the global heavy-content budget so later fields are omitted', () => {
        // Each event carries a field just under the per-field cap; enough events to blow the total budget.
        const perField = 'y'.repeat(TRACE_MAX_FIELD_CHARS - 100)
        const eventCount = Math.ceil(TRACE_MAX_TOTAL_HEAVY_CHARS / TRACE_MAX_FIELD_CHARS) + 3
        const events = Array.from({ length: eventCount }, () => makeEvent({ $ai_output: perField }))
        const results = [{ id: 't1', events }]

        const summary = truncateTraceContent(results)

        expect(summary.truncated).toBe(true)
        const outputs = (results[0]!.events as any[]).map((e) => e.properties.$ai_output as string)
        const retained = outputs.reduce((sum, v) => sum + v.length, 0)
        // Total retained heavy content stays within the budget plus a small marker allowance.
        expect(retained).toBeLessThanOrEqual(TRACE_MAX_TOTAL_HEAVY_CHARS + eventCount * 200)
        expect(outputs.some((v) => v.includes('omitted'))).toBe(true)
    })

    it('is a no-op for non-array input', () => {
        expect(truncateTraceContent(null)).toEqual({ truncated: false, omittedEvents: 0 })
        expect(truncateTraceContent({ not: 'an array' })).toEqual({ truncated: false, omittedEvents: 0 })
    })
})
