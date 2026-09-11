import { describe, expect, it } from 'vitest'

import { STRUCTURED_CONTENT_ONLY_TEXT, estimateResponseTokens, type ToolResultPayload } from '@/lib/build-tool-result'
import { RESPONSE_TRUNCATION_KEY, capResponseToClientBudget } from '@/lib/response-budget'

const CODEX_BUDGET = 9_000

function textPayload(text: string): ToolResultPayload {
    return { content: [{ type: 'text', text }] }
}

/** A tabular result of the shape `formatResponse` emits, one row per line. */
function table(rows: number): string {
    const lines = ['id,name,value']
    for (let i = 0; i < rows; i++) {
        lines.push(`${i},row-${i},${'x'.repeat(80)}`)
    }
    return lines.join('\n')
}

describe('capResponseToClientBudget', () => {
    it('returns a response that fits untouched', () => {
        const response = textPayload(table(10))

        const capped = capResponseToClientBudget(response, CODEX_BUDGET)

        expect(capped.response).toBe(response)
        expect(capped.overflowTokens).toBeUndefined()
    })

    it('leaves the response untouched when the client has no budget', () => {
        const response = textPayload(table(20_000))

        expect(capResponseToClientBudget(response, undefined).response).toBe(response)
    })

    it('brings an oversized text response inside the budget and says how to ask for less', () => {
        const response = textPayload(table(20_000))
        expect(estimateResponseTokens(response)).toBeGreaterThan(CODEX_BUDGET * 10)

        const capped = capResponseToClientBudget(response, CODEX_BUDGET)

        expect(estimateResponseTokens(capped.response)).toBeLessThanOrEqual(CODEX_BUDGET)
        expect(capped.overflowTokens).toBe(estimateResponseTokens(response))
        const text = capped.response.content[0]!.text
        expect(text).toContain('Result shortened to fit this client')
        expect(text).toContain('add filters')
    })

    it('cuts the kept text at a line boundary so no row arrives half-written', () => {
        const capped = capResponseToClientBudget(textPayload(table(20_000)), CODEX_BUDGET)

        const [kept] = capped.response.content[0]!.text.split('\n\nResult shortened')
        const rows = kept!.split('\n')
        expect(rows.length).toBeGreaterThan(1)
        expect(rows.length).toBeLessThan(20_000)
        for (const row of rows.slice(1)) {
            expect(row).toMatch(/^\d+,row-\d+,x{80}$/)
        }
    })

    it('projects an oversized structuredContent payload to valid JSON that keeps the pointer fields', () => {
        const response: ToolResultPayload = {
            content: [{ type: 'text', text: STRUCTURED_CONTENT_ONLY_TEXT }],
            structuredContent: {
                results: Array.from({ length: 20_000 }, (_, i) => ({ id: i, blob: 'x'.repeat(200) })),
                _posthogUrl: 'https://us.posthog.com/project/2/insights/abc',
            },
        }

        const capped = capResponseToClientBudget(response, CODEX_BUDGET)

        expect(estimateResponseTokens(capped.response)).toBeLessThanOrEqual(CODEX_BUDGET)
        const projected = capped.response.structuredContent!
        // The short trailing field survives the oversized one, so the agent still has
        // somewhere to read the rest from.
        expect(projected._posthogUrl).toBe('https://us.posthog.com/project/2/insights/abc')
        const kept = projected.results as unknown[]
        expect(kept.length).toBeGreaterThan(0)
        expect(kept.length).toBeLessThan(20_000)
        expect(kept[0]).toEqual({ id: 0, blob: 'x'.repeat(200) })
        expect(projected[RESPONSE_TRUNCATION_KEY]).toMatchObject({ shortenedFields: ['results'] })
    })

    it('records a field it could not fit at all as omitted, and keeps the fields that do fit', () => {
        const response: ToolResultPayload = {
            content: [{ type: 'text', text: STRUCTURED_CONTENT_ONLY_TEXT }],
            structuredContent: { blob: 'x'.repeat(200_000), id: 7, results: [] },
        }

        const capped = capResponseToClientBudget(response, CODEX_BUDGET)

        expect(estimateResponseTokens(capped.response)).toBeLessThanOrEqual(CODEX_BUDGET)
        expect(capped.response.structuredContent!.id).toBe(7)
        expect(capped.response.structuredContent!.blob).toBeUndefined()
        // An empty array fits, so it stays an empty array. Dropping it would change the
        // shape a caller reads `results.length` from.
        expect(capped.response.structuredContent!.results).toEqual([])
        expect(capped.response.structuredContent![RESPONSE_TRUNCATION_KEY]).toMatchObject({ omittedFields: ['blob'] })
    })
})
