import { describe, expect, it } from 'vitest'

import { compactTrace, compactTraceResults, MAX_TRACE_CHARS, PER_VALUE_CHAR_LIMIT } from '@/lib/trace-compaction'

describe('compactTrace', () => {
    it('truncates a long string property while leaving short values and structure intact', () => {
        const hugeInput = 'x'.repeat(PER_VALUE_CHAR_LIMIT + 5_000)
        const trace = {
            id: 'trace-1',
            totalCost: 0.42,
            events: [{ id: 'e1', event: '$ai_generation', properties: { $ai_input: hugeInput, $ai_model: 'gpt-4' } }],
        }

        const result = compactTrace(trace) as any

        expect(result.id).toBe('trace-1')
        expect(result.totalCost).toBe(0.42)
        expect(result.events[0].properties.$ai_model).toBe('gpt-4')
        const compactedInput = result.events[0].properties.$ai_input as string
        expect(compactedInput.length).toBeLessThan(hugeInput.length)
        expect(compactedInput).toContain('truncated')
        expect(compactedInput.startsWith('x'.repeat(PER_VALUE_CHAR_LIMIT))).toBe(true)
    })

    it('returns a within-budget trace unchanged without a truncation flag', () => {
        const trace = { id: 'trace-1', totalCost: 1, events: [{ id: 'e1', properties: { $ai_input: 'hello' } }] }

        const result = compactTrace(trace) as any

        expect(result._truncated).toBeUndefined()
        expect(result).toEqual(trace)
    })

    it('drops trailing events and flags the omission when a trace exceeds the size budget', () => {
        const events = Array.from({ length: 200 }, (_, i) => ({
            id: `e${i}`,
            event: '$ai_span',
            properties: { blob: 'y'.repeat(PER_VALUE_CHAR_LIMIT) },
        }))
        const result = compactTrace({ id: 'trace-1', events }) as any

        expect(result._truncated.totalEvents).toBe(200)
        expect(result._truncated.omittedEvents).toBeGreaterThan(0)
        expect(result.events.length).toBe(200 - result._truncated.omittedEvents)
        expect(result.events.length).toBeGreaterThanOrEqual(1)
        expect(JSON.stringify(result).length).toBeLessThanOrEqual(MAX_TRACE_CHARS)
    })

    it('caps a single event whose value is a large collection of individually-small strings', () => {
        // No single string exceeds the per-value limit, so per-value truncation
        // alone would let this event through at ~2MB. The budget must still bind.
        const bigArray = Array.from({ length: 300 }, () => 'z'.repeat(PER_VALUE_CHAR_LIMIT - 1_000))
        const result = compactTrace({ id: 'trace-1', events: [{ id: 'e1', properties: { $ai_input: bigArray } }] })

        expect(JSON.stringify(result).length).toBeLessThanOrEqual(MAX_TRACE_CHARS)
    })

    it('caps oversized trace-level state even when there are no events', () => {
        const bigState = Array.from({ length: 300 }, () => 'w'.repeat(PER_VALUE_CHAR_LIMIT - 1_000))
        const result = compactTrace({ id: 'trace-1', inputState: bigState, events: [] })

        expect(JSON.stringify(result).length).toBeLessThanOrEqual(MAX_TRACE_CHARS)
    })

    it('preserves an own __proto__ key in a trace payload instead of corrupting the clone', () => {
        // JSON.parse creates __proto__ as an own enumerable data property.
        const trace = JSON.parse('{"id":"trace-1","events":[{"properties":{"payload":{"__proto__":"custom"}}}]}')

        const result = compactTrace(trace) as any

        const payload = result.events[0].properties.payload
        expect(Object.getOwnPropertyDescriptor(payload, '__proto__')?.value).toBe('custom')
    })
})

describe('compactTraceResults', () => {
    it('compacts the single trace returned by query-llm-trace', () => {
        const hugeInput = 'z'.repeat(PER_VALUE_CHAR_LIMIT + 1)
        const results = compactTraceResults([{ id: 't1', events: [{ properties: { $ai_input: hugeInput } }] }]) as any[]

        expect(results[0].events[0].properties.$ai_input as string).toContain('truncated')
    })

    it('bounds the combined size of a multi-trace list and flags dropped traces', () => {
        // Each trace fits its own per-trace budget (~36K after compaction), but
        // 40 of them do not fit the shared total budget — the aggregate cap must
        // drop the tail. Uses many sub-per-value-limit strings so per-value
        // truncation doesn't shrink a trace down on its own.
        const chunk = 'q'.repeat(PER_VALUE_CHAR_LIMIT - 1_000)
        const traces = Array.from({ length: 40 }, (_, i) => ({
            id: `t${i}`,
            events: [{ id: `e${i}`, properties: { $ai_input: [chunk, chunk, chunk, chunk] } }],
        }))
        const results = compactTraceResults(traces) as any[]

        expect(JSON.stringify(results).length).toBeLessThanOrEqual(MAX_TRACE_CHARS + 5_000)
        const sentinel = results[results.length - 1]
        expect(sentinel._truncated.omittedTraces).toBeGreaterThan(0)
        expect(sentinel._truncated.totalTraces).toBe(40)
    })

    it('passes a non-array result through untouched', () => {
        expect(compactTraceResults(null)).toBeNull()
    })
})
