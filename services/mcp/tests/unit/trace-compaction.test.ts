import { describe, expect, it } from 'vitest'

import {
    MAX_SUMMARY_CHARS,
    MAX_TRACE_CHARS,
    PER_VALUE_CHAR_LIMIT,
    compactTrace,
    compactTraceResults,
} from '@/lib/trace-compaction'

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

    it('caps an event carrying an oversized property name, not just an oversized value', () => {
        // The value is tiny; the key is ~900K. Per-value truncation never looks at
        // keys, so the budget accounting must charge the key or it slips past the cap.
        const bigKey = 'k'.repeat(900_000)
        const result = compactTrace({ id: 'trace-1', events: [{ id: 'e1', properties: { [bigKey]: 'v' } }] })

        expect(JSON.stringify(result).length).toBeLessThanOrEqual(MAX_TRACE_CHARS)
    })

    it('caps oversized trace-level state even when there are no events', () => {
        const bigState = Array.from({ length: 300 }, () => 'w'.repeat(PER_VALUE_CHAR_LIMIT - 1_000))
        const result = compactTrace({ id: 'trace-1', inputState: bigState, events: [] })

        expect(JSON.stringify(result).length).toBeLessThanOrEqual(MAX_TRACE_CHARS)
    })

    it.each([
        ['double quotes', '"'],
        ['newlines', '\n'],
        ['control characters', String.fromCharCode(1)],
    ])('holds the cap for content made of %s, which JSON escaping inflates', (_label, character) => {
        // Budgeting on raw character count treats these as one character each while
        // JSON encodes them as two or six, so the walk's estimate is several times
        // under the real encoded size.
        const events = Array.from({ length: 500 }, (_, i) => ({
            id: `e${i}`,
            properties: { $ai_input: character.repeat(PER_VALUE_CHAR_LIMIT) },
        }))

        const result = compactTrace({ id: 'trace-1', events })

        expect(JSON.stringify(result).length).toBeLessThanOrEqual(MAX_TRACE_CHARS)
    })

    it('holds the cap for a trace that encodes to more than 64MB', () => {
        // The MCP transport rejects frames past 64MB, so the cap has to bind on
        // input that large rather than only on the traces seen so far.
        const chunk = 'x'.repeat(PER_VALUE_CHAR_LIMIT)
        const trace = {
            id: 'trace-1',
            events: Array.from({ length: 7_000 }, (_, i) => ({
                id: `e${i}`,
                properties: { $ai_input: chunk, $ai_output_choices: chunk },
            })),
        }
        expect(JSON.stringify(trace).length).toBeGreaterThan(64 * 1024 * 1024)

        const result = compactTrace(trace)

        expect(JSON.stringify(result).length).toBeLessThanOrEqual(MAX_TRACE_CHARS)
        expect((result as any)._truncated.totalEvents).toBe(7_000)
    })

    it('preserves an own __proto__ key in a trace payload instead of corrupting the clone', () => {
        // JSON.parse creates __proto__ as an own enumerable data property.
        const trace = JSON.parse('{"id":"trace-1","events":[{"properties":{"payload":{"__proto__":"custom"}}}]}')

        const result = compactTrace(trace) as any

        const payload = result.events[0].properties.payload
        expect(Object.getOwnPropertyDescriptor(payload, '__proto__')?.value).toBe('custom')
    })
})

describe('compactTrace summary detail', () => {
    const trace = {
        id: 'trace-1',
        totalCost: 0.42,
        inputState: { messages: [{ role: 'user', content: 'p'.repeat(5_000) }] },
        events: [
            {
                id: 'e1',
                event: '$ai_generation',
                createdAt: '2026-09-02T11:30:23Z',
                properties: {
                    $ai_model: 'gpt-4',
                    $ai_latency: 1.5,
                    $ai_tools_called: ['search'],
                    $ai_is_error: false,
                    $ai_input: 'i'.repeat(5_000),
                    $ai_output_choices: 'o'.repeat(5_000),
                    custom_payload: 'c'.repeat(5_000),
                },
            },
        ],
    }

    it('keeps navigation metadata verbatim and previews everything else', () => {
        const result = compactTrace(trace, MAX_SUMMARY_CHARS, 'summary') as any

        const properties = result.events[0].properties
        expect(properties.$ai_model).toBe('gpt-4')
        expect(properties.$ai_latency).toBe(1.5)
        expect(properties.$ai_tools_called).toEqual(['search'])
        expect(properties.$ai_is_error).toBe(false)
        expect(properties.$ai_input).toContain('truncated')
        expect(properties.$ai_output_choices).toContain('truncated')
        expect(properties.custom_payload).toContain('truncated')
        expect(result.events[0].createdAt).toBe('2026-09-02T11:30:23Z')
        expect(result.totalCost).toBe(0.42)
        expect(result._detail.mode).toBe('summary')
    })

    it('previews a structured prompt with readable content, not an empty shell', () => {
        // `$ai_input` is an array of message objects, so a preview only helps if the
        // walk's per-item allowances leave room to descend into it.
        const messages = [
            { role: 'system', content: 's'.repeat(2_000) },
            { role: 'user', content: 'Why did the checkout funnel drop?' },
        ]

        const result = compactTrace(
            { id: 'trace-1', events: [{ id: 'e1', properties: { $ai_input: messages } }] },
            MAX_SUMMARY_CHARS,
            'summary'
        ) as any

        const preview = result.events[0].properties.$ai_input
        expect(preview[0].role).toBe('system')
        expect(preview[0].content).toContain('sss')
        expect(preview[0].content).toContain('truncated')
    })

    it('returns far less than the same trace at full detail', () => {
        const summary = JSON.stringify(compactTrace(trace, MAX_SUMMARY_CHARS, 'summary')).length
        const full = JSON.stringify(compactTrace(trace, MAX_TRACE_CHARS, 'full')).length

        expect(summary).toBeLessThan(full / 5)
    })

    it('still drops events when a summarized trace outgrows the summary cap', () => {
        const events = Array.from({ length: 5_000 }, (_, i) => ({
            id: `e${i}`,
            properties: { $ai_input: 'y'.repeat(PER_VALUE_CHAR_LIMIT) },
        }))

        const result = compactTrace({ id: 'trace-1', events }, MAX_SUMMARY_CHARS, 'summary') as any

        expect(JSON.stringify(result).length).toBeLessThanOrEqual(MAX_SUMMARY_CHARS)
        expect(result._truncated.omittedEvents).toBeGreaterThan(0)
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

    it('bounds a summarized list to the tighter summary cap', () => {
        const traces = Array.from({ length: 200 }, (_, i) => ({
            id: `t${i}`,
            events: Array.from({ length: 20 }, () => ({ properties: { $ai_input: 'r'.repeat(5_000) } })),
        }))

        const results = compactTraceResults(traces, 'summary')

        expect(JSON.stringify(results).length).toBeLessThanOrEqual(MAX_SUMMARY_CHARS)
    })

    it('passes a non-array result through untouched', () => {
        expect(compactTraceResults(null)).toBeNull()
    })
})
