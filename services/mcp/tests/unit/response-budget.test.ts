import { describe, expect, it } from 'vitest'

import {
    STRUCTURED_CONTENT_ONLY_TEXT,
    buildToolResultPayload,
    estimateResponseTokens,
    type ToolResultPayload,
} from '@/lib/build-tool-result'
import { MCPClientProfile } from '@/lib/client-detection'
import { RESPONSE_TRUNCATION_KEY, capResponseToClientBudget } from '@/lib/response-budget'
import { withInformationalResponse } from '@/tools/tool-utils'
import { POSTHOG_META_KEY } from '@/tools/types'

const CODEX_BUDGET = 9_000

function textPayload(text: string): ToolResultPayload {
    return { content: [{ type: 'text', text }] }
}

/** Rows of the shape a query handler returns, wide enough to overflow any client budget. */
function blobRows(count: number): Record<string, unknown>[] {
    return Array.from({ length: count }, (_, i) => ({ id: i, blob: 'x'.repeat(200) }))
}

/** A tabular result of the shape `formatResponse` emits, one row per line. */
function table(rows: number): string {
    const lines = ['id,name,value']
    for (let i = 0; i < rows; i++) {
        lines.push(`${i},row-${i},${'x'.repeat(80)}`)
    }
    return lines.join('\n')
}

/** A tabular result carrying one row wider than half a Codex budget, as a properties dump is. */
function wideRowTable(): string {
    const lines = ['id,properties', `1,${'P'.repeat(40_000)}`]
    for (let i = 2; i < 100; i++) {
        lines.push(`${i},small`)
    }
    return lines.join('\n')
}

function keptText(capped: ToolResultPayload): string {
    return capped.content[0]!.text.split('\n\nResult shortened')[0]!
}

describe('capResponseToClientBudget', () => {
    it('returns a response that fits untouched', () => {
        const response = textPayload(table(10))

        const capped = capResponseToClientBudget(response, CODEX_BUDGET)

        expect(capped.response).toBe(response)
        expect(capped.overflowTokens).toBeUndefined()
    })

    it('leaves an oversized response untouched for a client with no known limit', () => {
        const response = textPayload(table(20_000))
        const { maxResponseTokens } = new MCPClientProfile({ clientName: 'cursor' }).capabilities

        const capped = capResponseToClientBudget(response, maxResponseTokens)

        expect(capped.response).toBe(response)
        expect(capped.overflowTokens).toBeUndefined()
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

    // A row wider than half the budget used to fall through the line-boundary cut, so the
    // kept text ended inside that row and a clipped value read as a complete one.
    it('drops a row too wide to fit rather than keeping a fragment of it', () => {
        const text = wideRowTable()

        const capped = capResponseToClientBudget(textPayload(text), CODEX_BUDGET)

        const sourceLines = new Set(text.split('\n'))
        for (const row of keptText(capped.response).split('\n')) {
            expect(sourceLines.has(row)).toBe(true)
        }
    })

    // An informational result quarantines workspace data in a tag pair the agent must not
    // act on. Clipping the text dropped the closing tag and left the cap's own instruction
    // inside the block that tells the agent to ignore instructions.
    it('keeps a shortened informational result inside a balanced tag pair, with the notice outside', () => {
        const wrapped = withInformationalResponse({ results: blobRows(20_000) }, 'notebook-content')
        const built = buildToolResultPayload({ handlerResult: wrapped, toolName: 'notebooks-get', params: {} })

        const capped = capResponseToClientBudget(built, CODEX_BUDGET)

        const text = capped.response.content[0]!.text
        expect(estimateResponseTokens(capped.response)).toBeLessThanOrEqual(CODEX_BUDGET)
        expect(text.match(/<notebook-content /g)).toHaveLength(1)
        expect(text.match(/<\/notebook-content>/g)).toHaveLength(1)
        expect(text.indexOf('Result shortened')).toBeGreaterThan(text.indexOf('</notebook-content>'))
        expect(text).toContain('"id":0')
    })

    // Text with no line to cut at is prose, where dropping the prefix would leave the
    // agent the notice and nothing else.
    it('keeps the prefix of a newline-free response', () => {
        const capped = capResponseToClientBudget(textPayload('word '.repeat(20_000)), CODEX_BUDGET)

        expect(estimateResponseTokens(capped.response)).toBeLessThanOrEqual(CODEX_BUDGET)
        expect(keptText(capped.response).length).toBeGreaterThan(1_000)
    })

    // `output_format: 'json'` and `exec --json` return a serialized value the caller
    // parses, so a shortened one has to still parse. Clipping the text and appending
    // the notice left a JSON prefix followed by prose.
    it('keeps an oversized JSON object response parseable and says what it left out', () => {
        const payload = { results: blobRows(20_000), _posthogUrl: 'https://us.posthog.com/project/2/insights/abc' }

        const capped = capResponseToClientBudget(textPayload(JSON.stringify(payload)), CODEX_BUDGET)

        expect(estimateResponseTokens(capped.response)).toBeLessThanOrEqual(CODEX_BUDGET)
        const parsed = JSON.parse(capped.response.content[0]!.text)
        expect(parsed._posthogUrl).toBe(payload._posthogUrl)
        expect(parsed.results.length).toBeGreaterThan(0)
        expect(parsed.results.length).toBeLessThan(20_000)
        expect(parsed[RESPONSE_TRUNCATION_KEY].notice).toContain('Result shortened to fit this client')
    })

    it('keeps an oversized JSON array response a list, closed by a truncation sentinel', () => {
        const all = blobRows(20_000)

        const capped = capResponseToClientBudget(textPayload(JSON.stringify(all)), CODEX_BUDGET)

        expect(estimateResponseTokens(capped.response)).toBeLessThanOrEqual(CODEX_BUDGET)
        const parsed = JSON.parse(capped.response.content[0]!.text)
        expect(Array.isArray(parsed)).toBe(true)
        expect(parsed[0]).toEqual(all[0])
        expect(parsed.at(-1)[RESPONSE_TRUNCATION_KEY]).toMatchObject({ totalItems: 20_000 })
        expect(parsed.length).toBeLessThan(20_000)
    })

    // The builder picks the JSON text channel from the caller's `output_format` or the
    // tool's own metadata, so the cap has to keep both parseable end to end.
    it.each(['the caller asks for json', 'the tool pins json'] as const)(
        'keeps a built response parseable when %s',
        (selection) => {
            const built = buildToolResultPayload({
                handlerResult: {
                    results: blobRows(20_000),
                    _posthogUrl: 'https://us.posthog.com/project/2/insights/abc',
                },
                toolName: 'query-web-stats',
                params: selection === 'the caller asks for json' ? { output_format: 'json' } : {},
                ...(selection === 'the tool pins json'
                    ? { toolMeta: { [POSTHOG_META_KEY]: { outputFormat: 'json' as const } } }
                    : {}),
            })

            const capped = capResponseToClientBudget(built, CODEX_BUDGET)

            expect(() => JSON.parse(capped.response.content[0]!.text)).not.toThrow()
            expect(capped.overflowTokens).toBeGreaterThan(CODEX_BUDGET)
        }
    )

    it('projects an oversized structuredContent payload to valid JSON that keeps the pointer fields', () => {
        const response: ToolResultPayload = {
            content: [{ type: 'text', text: STRUCTURED_CONTENT_ONLY_TEXT }],
            structuredContent: {
                results: blobRows(20_000),
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
