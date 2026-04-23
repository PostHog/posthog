import { describe, expect, it } from 'vitest'

import { buildToolResultPayload } from '@/lib/build-tool-result'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, POSTHOG_META_KEY } from '@/tools/types'

// Simulates a `query-trends` handler return value: a UI-resource tool that
// carries both the raw `results` object and a pre-formatted pipe-delimited table
// surfaced via the override key.
const FORMATTED_TABLE = [
    'Date|$pageview',
    '2026-04-14|0',
    '2026-04-15|0',
    '2026-04-16|25',
    '2026-04-17|0',
    '2026-04-18|0',
    '2026-04-19|0',
    '2026-04-20|3',
    '2026-04-21|0',
].join('\n')

function queryTrendsHandlerResult(withFormatted = true): Record<string, unknown> {
    return {
        results: [
            {
                data: [0, 0, 25, 0, 0, 0, 3, 0],
                labels: [
                    '14-Apr-2026',
                    '15-Apr-2026',
                    '16-Apr-2026',
                    '17-Apr-2026',
                    '18-Apr-2026',
                    '19-Apr-2026',
                    '20-Apr-2026',
                    '21-Apr-2026',
                ],
                count: 28,
                label: '$pageview',
            },
        ],
        _posthogUrl: 'http://localhost:8010/project/1/insights/new#q=%7B...',
        ...(withFormatted ? { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: FORMATTED_TABLE } : {}),
    }
}

// Same `_meta` shape that `createQueryWrapper` produces for a UI-resource query tool.
const queryTrendsToolMeta = {
    ui: { resourceUri: 'ui://posthog/query-results.html' },
} as const

describe('buildToolResultPayload — query-trends for Claude Code', () => {
    it('returns formatted table as text AND suppresses structuredContent for claude-code', () => {
        const payload = buildToolResultPayload({
            handlerResult: queryTrendsHandlerResult(),
            toolMeta: queryTrendsToolMeta,
            toolName: 'query-trends',
            params: { series: [{ event: '$pageview', kind: 'EventsNode' }] },
            clientName: 'claude-code',
            distinctId: 'test-distinct-id',
        })

        // The model should see the formatted table — not a JSON dump.
        expect(payload.content).toEqual([{ type: 'text', text: FORMATTED_TABLE }])
        // No structuredContent: Claude Code would otherwise prefer it over text,
        // defeating the purpose of the formatted_results override.
        expect(payload).not.toHaveProperty('structuredContent')
    })

    it.each([
        ['claude-code'],
        ['Claude Code'], // whitespace variant — normalizer strips it
        ['claude-code-cli'],
        ['claude-code/1.2.3'],
        ['cline'],
        ['cline-bot'],
        ['continue'],
        ['codex'],
        ['windsurf'],
        ['zed'],
        ['aider'],
        ['github.copilot'],
    ])('suppresses structuredContent for coding agent %s', (clientName) => {
        const payload = buildToolResultPayload({
            handlerResult: queryTrendsHandlerResult(),
            toolMeta: queryTrendsToolMeta,
            toolName: 'query-trends',
            params: {},
            clientName,
            distinctId: 'd',
        })

        expect(payload.content[0]!.text).toBe(FORMATTED_TABLE)
        expect(payload).not.toHaveProperty('structuredContent')
    })

    it('keeps structuredContent for Cursor (it reads text for the model, structured for UI)', () => {
        const payload = buildToolResultPayload({
            handlerResult: queryTrendsHandlerResult(),
            toolMeta: queryTrendsToolMeta,
            toolName: 'query-trends',
            params: {},
            clientName: 'cursor',
            distinctId: 'test-distinct-id',
        })

        expect(payload.content[0]!.text).toBe(FORMATTED_TABLE)
        expect(payload.structuredContent).toMatchObject({
            results: expect.any(Array),
            _posthogUrl: expect.any(String),
            _analytics: { distinctId: 'test-distinct-id', toolName: 'query-trends' },
        })
        // Override key must not leak into structuredContent.
        expect(payload.structuredContent).not.toHaveProperty(POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY)
    })

    it.each([['Claude Desktop'], ['claude-desktop'], ['mcp-inspector'], [undefined]])(
        'keeps structuredContent for non-coding client %s',
        (clientName) => {
            const payload = buildToolResultPayload({
                handlerResult: queryTrendsHandlerResult(),
                toolMeta: queryTrendsToolMeta,
                toolName: 'query-trends',
                params: {},
                clientName,
                distinctId: 'd',
            })

            expect(payload.content[0]!.text).toBe(FORMATTED_TABLE)
            expect(payload.structuredContent).not.toBeUndefined()
        }
    )

    it('keeps structuredContent when caller explicitly passes output_format=json (even on claude-code)', () => {
        const payload = buildToolResultPayload({
            handlerResult: queryTrendsHandlerResult(),
            toolMeta: queryTrendsToolMeta,
            toolName: 'query-trends',
            params: { output_format: 'json' },
            clientName: 'claude-code',
            distinctId: 'd',
        })

        // Text still carries the formatted override (the override wins unconditionally)...
        expect(payload.content[0]!.text).toBe(FORMATTED_TABLE)
        // ...but structuredContent is no longer suppressed — the caller opted into JSON.
        expect(payload.structuredContent).not.toBeUndefined()
        expect(payload.structuredContent).toMatchObject({
            results: expect.any(Array),
            _posthogUrl: expect.any(String),
        })
    })

    it('does NOT suppress structuredContent when there is no formatted_results override', () => {
        // If the backend didn't return formatted_results (unsupported query type, EE unavailable,
        // etc.), the wrapper has nothing to put in text besides the TOON-encoded raw object.
        // In that case we must keep structuredContent so Claude Code at least sees the data.
        const payload = buildToolResultPayload({
            handlerResult: queryTrendsHandlerResult(/* withFormatted */ false),
            toolMeta: queryTrendsToolMeta,
            toolName: 'query-trends',
            params: {},
            clientName: 'claude-code',
            distinctId: 'd',
        })

        expect(payload.structuredContent).not.toBeUndefined()
        // Text is TOON-encoded rawResult, not JSON, not the formatted table.
        expect(payload.content[0]!.text).not.toBe(FORMATTED_TABLE)
        expect(payload.content[0]!.text).toContain('_posthogUrl')
    })

    it('embeds analytics metadata in structuredContent when present (non-suppressed case)', () => {
        const payload = buildToolResultPayload({
            handlerResult: queryTrendsHandlerResult(),
            toolMeta: queryTrendsToolMeta,
            toolName: 'query-trends',
            params: {},
            clientName: 'claude-desktop',
            distinctId: 'user-abc-123',
        })

        expect(payload.structuredContent).toMatchObject({
            _analytics: {
                distinctId: 'user-abc-123',
                toolName: 'query-trends',
            },
        })
    })

    it('omits structuredContent for tools without a UI resource', () => {
        // Non-UI tools (e.g. a hypothetical `query-logs` without a UI app) must never emit
        // structuredContent regardless of client or formatted_results.
        const payload = buildToolResultPayload({
            handlerResult: queryTrendsHandlerResult(),
            toolMeta: undefined,
            toolName: 'whatever',
            params: {},
            clientName: 'cursor',
            distinctId: 'd',
        })

        expect(payload).not.toHaveProperty('structuredContent')
        expect(payload.content[0]!.text).toBe(FORMATTED_TABLE)
    })
})

describe('buildToolResultPayload — non-query use cases', () => {
    it('passes string handler results through verbatim (no character-indexed expansion)', () => {
        // Regression guard for the original bug: `execute-sql` and other
        // string-returning handlers must not be object-rest-destructured.
        const sqlResult = 'You are given a table...\n\nmarker|answer\nfix_applied|42'

        const payload = buildToolResultPayload({
            handlerResult: sqlResult,
            toolMeta: undefined,
            toolName: 'execute-sql',
            params: {},
            clientName: 'claude-code',
            distinctId: undefined,
        })

        expect(payload.content[0]!.text).toBe(sqlResult)
        expect(payload.content[0]!.text).not.toMatch(/"0":\s*"./)
        expect(payload).not.toHaveProperty('structuredContent')
    })

    it('JSON-encodes rawResult when tool-level outputFormat=json is configured', () => {
        // For tools like `query-llm-traces-list` that advertise JSON output at the tool level
        // (via `_meta[POSTHOG_META_KEY].outputFormat === 'json'`), text is JSON, not TOON.
        const payload = buildToolResultPayload({
            handlerResult: { results: [], _posthogUrl: 'http://...' },
            toolMeta: { [POSTHOG_META_KEY]: { outputFormat: 'json' } },
            toolName: 'query-llm-traces-list',
            params: {},
            clientName: 'claude-code',
            distinctId: undefined,
        })

        expect(() => JSON.parse(payload.content[0]!.text)).not.toThrow()
        expect(JSON.parse(payload.content[0]!.text)).toEqual({
            results: [],
            _posthogUrl: 'http://...',
        })
    })
})
