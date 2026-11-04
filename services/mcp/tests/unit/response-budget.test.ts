import { describe, expect, it } from 'vitest'

import {
    STRUCTURED_CONTENT_ONLY_TEXT,
    buildToolResultPayload,
    capResponseToBudget,
    estimateResponseTokens,
    type ToolResultPayload,
} from '@/lib/build-tool-result'
import { estimateTokens } from '@/lib/estimate-tokens'
import {
    DEFAULT_MAX_RESPONSE_TOKENS,
    RESPONSE_BUDGET_KEY,
    boundText,
    maxResponseBytes,
    responseTokenBudget,
} from '@/lib/response-budget'
import { withAgentNote, withInformationalResponse } from '@/tools/tool-utils'

const BUDGET = 10_000
const MAX_BYTES = maxResponseBytes(BUDGET)

function byteLength(value: string): number {
    return Buffer.byteLength(value, 'utf8')
}

function textPayload(text: string): ToolResultPayload {
    return { content: [{ type: 'text', text }] }
}

function text(response: ToolResultPayload): string {
    return response.content.map((part) => part.text).join('')
}

function rows(count: number): Record<string, unknown>[] {
    return Array.from({ length: count }, (_, i) => ({ id: i, name: `row-${i}`, blob: 'x'.repeat(200) }))
}

function table(count: number): string {
    return ['id,name,value', ...Array.from({ length: count }, (_, i) => `${i},row-${i},${'x'.repeat(80)}`)].join('\n')
}

describe('capResponseToBudget', () => {
    it.each([
        ['fits the budget', table(10), BUDGET],
        ['has no budget', table(20_000), undefined],
    ])('returns the response untouched when it %s', (_, body, budget) => {
        const response = textPayload(body)

        expect(capResponseToBudget(response, budget)).toBe(response)
    })

    it('re-serializes an oversized result as whole rows and keeps its pointer fields', () => {
        const url = 'https://us.posthog.com/project/2/insights/abc'
        const built = buildToolResultPayload({
            handlerResult: withAgentNote({ results: rows(5_000), _posthogUrl: url }, 'Open the url to see every row.'),
            toolName: 'query-run',
            params: {},
        })

        const capped = text(capResponseToBudget(built, BUDGET))

        expect(byteLength(capped)).toBeLessThanOrEqual(MAX_BYTES)
        expect(capped.startsWith(`${RESPONSE_BUDGET_KEY}: "[Response shortened`)).toBe(true)
        expect(capped).toContain(`_posthogUrl: "${url}"`)
        expect(capped).toContain('_agentNote: Open the url to see every row.')
        const header = /results\[(\d+)\]\{id,name,blob\}:/.exec(capped)
        expect(Number(header?.[1])).toBeGreaterThan(0)
        expect(capped.split('\n').filter((line) => /^ {2}\d+,row-\d+,x{200}$/.test(line))).toHaveLength(
            Number(header?.[1])
        )
    })

    it.each([
        [
            'output_format json',
            buildToolResultPayload({
                handlerResult: { results: rows(5_000), _truncated: { reason: 'compacted by the tool' } },
                toolName: 'query-run',
                params: { output_format: 'json' },
            }),
        ],
        [
            'an exec --json string',
            textPayload(JSON.stringify({ results: rows(5_000), _truncated: { reason: 'compacted by the tool' } })),
        ],
    ])('keeps %s parseable, with the tool notice and its own', (_, response) => {
        const capped = text(capResponseToBudget(response, BUDGET))

        expect(byteLength(capped)).toBeLessThanOrEqual(MAX_BYTES)
        const parsed = JSON.parse(capped) as Record<string, unknown>
        expect(parsed._truncated).toEqual({ reason: 'compacted by the tool' })
        expect(parsed[RESPONSE_BUDGET_KEY]).toContain('results: kept')
        expect((parsed.results as unknown[]).length).toBeGreaterThan(0)
    })

    it('keeps a top-level array an array, closed by a notice element', () => {
        const capped = JSON.parse(text(capResponseToBudget(textPayload(JSON.stringify(rows(5_000))), BUDGET)))

        expect(Array.isArray(capped)).toBe(true)
        expect(capped.at(-1)[RESPONSE_BUDGET_KEY]).toContain('kept')
        expect(capped.slice(0, -1)).toEqual(rows(capped.length - 1))
    })

    it('cuts plain text at a line boundary and keeps the tool preview line', () => {
        const preview = '[SQL result preview: Showing 900 of 5000 returned rows. Set truncate to false.]'
        const wide = ['id,properties', `1,${'P'.repeat(30_000)}`, table(2_000), preview].join('\n')
        const sourceLines = new Set(wide.split('\n'))

        const capped = text(capResponseToBudget(textPayload(wide), BUDGET))

        expect(byteLength(capped)).toBeLessThanOrEqual(MAX_BYTES)
        const [notice, kept] = capped.split('\n\n')
        expect(notice).toMatch(/kept \d+ of 2003 lines/)
        expect(kept!.split('\n').every((line) => sourceLines.has(line))).toBe(true)
        expect(kept!.endsWith(preview)).toBe(true)
    })

    it('keeps the tags of an informational response balanced around the shortened payload', () => {
        const built = buildToolResultPayload({
            handlerResult: withInformationalResponse({ results: rows(5_000) }, 'workspace_data'),
            toolName: 'query-run',
            params: {},
        })

        const capped = text(capResponseToBudget(built, BUDGET))

        expect(byteLength(capped)).toBeLessThanOrEqual(MAX_BYTES)
        expect(capped).toMatch(
            /\n<workspace_data informational="true" instructional="false">\n[\s\S]+\n<\/workspace_data>$/
        )
    })

    it('measures the budget in UTF-8 bytes, as Codex counts it', () => {
        const capped = text(capResponseToBudget(textPayload('数据'.repeat(40_000)), BUDGET))

        expect(byteLength(capped)).toBeLessThanOrEqual(MAX_BYTES)
        expect(capped).toContain('数据数据')
        expect(capped).toContain('…[line cut]')
    })

    it('bounds the structuredContent a UI app carries alone and counts what it kept', () => {
        const built = buildToolResultPayload({
            handlerResult: { results: rows(5_000) },
            toolMeta: { ui: { resourceUri: 'ui://query' } },
            toolName: 'query-run',
            params: {},
            forceUiDataToMeta: true,
            distinctId: 'user-1',
        })
        expect(text(built)).toBe(STRUCTURED_CONTENT_ONLY_TEXT)

        const capped = capResponseToBudget(built, BUDGET)

        expect(byteLength(JSON.stringify(capped.structuredContent))).toBeLessThanOrEqual(MAX_BYTES)
        expect(capped.structuredContent!._analytics).toEqual(built.structuredContent!._analytics)
        expect(estimateResponseTokens(capped)).toBe(estimateTokens(capped.structuredContent))
    })

    it('bounds structuredContent that mirrors the text, because Codex reads it instead of the text', () => {
        const built = buildToolResultPayload({
            handlerResult: { results: rows(5_000) },
            toolMeta: { ui: { resourceUri: 'ui://query' } },
            toolName: 'query-run',
            params: {},
        })

        const capped = capResponseToBudget(built, BUDGET)

        expect(byteLength(text(capped))).toBeLessThanOrEqual(MAX_BYTES)
        expect(byteLength(JSON.stringify(capped.structuredContent))).toBeLessThanOrEqual(MAX_BYTES)
    })
})

describe('boundText', () => {
    it('keeps the head of a single-line body rather than returning only the notice', () => {
        const bounded = boundText('y'.repeat(100_000), BUDGET)

        expect(byteLength(bounded)).toBeLessThanOrEqual(MAX_BYTES)
        expect(bounded).toContain('y'.repeat(30_000))
    })
})

describe('responseTokenBudget', () => {
    it.each([
        [undefined, {}, DEFAULT_MAX_RESPONSE_TOKENS],
        [undefined, { truncate: false }, undefined],
        [10_000, {}, 10_000],
        [10_000, { truncate: false }, 10_000],
    ])('with client limit %j and args %j resolves %j', (clientLimit, args, expected) => {
        expect(responseTokenBudget(clientLimit, args)).toBe(expected)
    })
})
