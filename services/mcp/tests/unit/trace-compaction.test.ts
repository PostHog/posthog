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

    it('drops trailing events and flags the omission when a trace exceeds the size budget', () => {
        // Each event serializes to ~11K chars, so the trace blows past MAX_TRACE_CHARS
        // even though no single string value is individually over the per-value limit.
        const events = Array.from({ length: 100 }, (_, i) => ({
            id: `e${i}`,
            event: '$ai_span',
            properties: { blob: 'y'.repeat(PER_VALUE_CHAR_LIMIT + 1_000) },
        }))
        const result = compactTrace({ id: 'trace-1', events }) as any

        expect(result._truncated.totalEvents).toBe(100)
        expect(result._truncated.omittedEvents).toBeGreaterThan(0)
        expect(result.events.length).toBe(100 - result._truncated.omittedEvents)
        expect(result.events.length).toBeGreaterThanOrEqual(1)
        expect(JSON.stringify(result).length).toBeLessThanOrEqual(MAX_TRACE_CHARS)
    })

    it('returns a within-budget trace unchanged without a truncation flag', () => {
        const trace = { id: 'trace-1', events: [{ id: 'e1', properties: { $ai_input: 'hello' } }] }

        const result = compactTrace(trace) as any

        expect(result._truncated).toBeUndefined()
        expect(result).toEqual(trace)
    })
})

describe('compactTraceResults', () => {
    it('compacts each trace in the results array', () => {
        const hugeInput = 'z'.repeat(PER_VALUE_CHAR_LIMIT + 1)
        const results = compactTraceResults([{ id: 't1', events: [{ properties: { $ai_input: hugeInput } }] }]) as any[]

        expect(results[0].events[0].properties.$ai_input as string).toContain('truncated')
    })

    it('passes a non-array result through untouched', () => {
        expect(compactTraceResults(null)).toBeNull()
    })
})
