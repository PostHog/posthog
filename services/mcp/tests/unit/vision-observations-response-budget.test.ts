import { describe, expect, it, vi } from 'vitest'

import { buildToolResultPayload, type ToolResultPayload } from '@/lib/build-tool-result'
import { estimateTokens } from '@/lib/estimate-tokens'
import { GENERATED_TOOLS } from '@/tools/generated/replay_vision'
import type { Context } from '@/tools/types'
import { APP_DATA_META_KEY } from '@/ui-apps/types'

/**
 * An agent that lists observations reads them to pick one, then retrieves that one in full. The
 * budget is what keeps the pick affordable: a day of scanning has to arrive whole, so the agent
 * never has to guess from a truncated page. The row payload is many times this on its own, which
 * is why the ceiling is set by what the flow needs rather than by what the rows happen to weigh.
 */
const DAILY_TOKEN_BUDGET = 4_000

const DAILY_ROW_COUNT = 50

const OBSERVATION_LIST_TOOL_META = { ui: { resourceUri: 'ui://posthog/vision-observation-list.html' } } as const

/** The scanner config frozen onto every row, and the segmented reasoning — the bulk of a row. */
function createScannerSnapshot(): Record<string, unknown> {
    return {
        name: 'Checkout card rejection',
        scanner_type: 'monitor',
        scanner_version: 4,
        model: 'model-a',
        provider: 'provider-a',
        emits_signals: true,
        verify_positives: 'shadow',
        scanner_config: {
            prompt: 'Watch the checkout step. '.repeat(60),
            question: 'Did the person see a card rejection they could not recover from?',
            tags: ['checkout', 'payment', 'rejection', 'retry', 'recovery'],
        },
    }
}

function createObservation(index: number): Record<string, unknown> {
    return {
        id: `00000000-0000-4000-8000-0000000000${String(index).padStart(2, '0')}`,
        session_id: `session-${index}`,
        scanner_id: '00000000-0000-4000-8000-00000000aaaa',
        scanner_origin: 'configured',
        status: 'succeeded',
        created_at: '2026-09-20T08:31:34Z',
        triggered_by: 'schedule',
        workflow_id: `workflow-${index}`,
        error_reason: null,
        summary_line: `[verdict=yes] The card was rejected twice on session ${index}.`,
        scanner_snapshot: createScannerSnapshot(),
        scanner_result: {
            signals_count: 1,
            verification: { mode: 'shadow', draws: ['yes', 'yes'], resolved_verdict: 'yes', served_verdict: 'yes' },
            model_output: {
                scanner_type: 'monitor',
                verdict: 'yes',
                confidence: 0.82,
                reasoning: 'The card form reports a decline and the person retries. '.repeat(20),
                reasoning_segments: Array.from({ length: 12 }, (_, segment) => ({
                    type: segment % 2 === 0 ? 'text' : 'chip',
                    text: 'The person retries the same card after the decline banner appears.',
                    timestamp_ms: segment * 9_000,
                })),
            },
        },
    }
}

function createMockContext(rowCount: number): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue({
                count: rowCount,
                next: null,
                previous: null,
                results: Array.from({ length: rowCount }, (_, index) => createObservation(index)),
            }),
            getProjectBaseUrl: () => 'https://us.posthog.com/project/7',
        },
        stateManager: { getProjectId: async () => 7 },
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
}

/**
 * Everything the model reads from one tool result. Both channels count: a client that prefers
 * `structuredContent` reads that instead of the text, so measuring the text alone would pass a
 * response that arrives as full rows.
 */
function modelVisibleTokens(payload: ToolResultPayload): number {
    const text = payload.content.map((part) => part.text).join('')
    return estimateTokens(text) + (payload.structuredContent ? estimateTokens(payload.structuredContent) : 0)
}

/** The projected rows of a TOON-encoded list: every line that opens with an observation id. */
function rowLines(text: string): string[] {
    return text.split('\n').filter((line) => /^\s+00000000-0000-4000-8000-\d/.test(line))
}

describe('vision-scanners-observations-list response budget', () => {
    const tool = GENERATED_TOOLS['vision-scanners-observations-list']!()

    /** Builds the response the way a client that reads `structuredContent` receives it. */
    async function callList(rowCount: number, params: Record<string, unknown> = {}): Promise<ToolResultPayload> {
        const handlerResult = await tool.handler(createMockContext(rowCount), {
            scanner_id: '00000000-0000-4000-8000-00000000aaaa',
            ...params,
        })
        return buildToolResultPayload({
            handlerResult,
            toolMeta: OBSERVATION_LIST_TOOL_META,
            toolName: 'vision-scanners-observations-list',
            params,
            suppressStructuredContentForFormattedResults: false,
        })
    }

    it('returns the asked-for rows and nothing wider on a small limit', async () => {
        const payload = await callList(3, { limit: 3 })
        const text = payload.content[0]!.text

        expect(text).toContain('results[3]{')
        expect(rowLines(text)).toHaveLength(3)
        expect(text).toContain('The card was rejected twice on session 0.')
        expect(text).not.toContain('Watch the checkout step.')
        expect(text).not.toContain('The card form reports a decline')
        expect(payload).not.toHaveProperty('structuredContent')
    })

    it(`keeps a ${DAILY_ROW_COUNT}-row day within the response budget`, async () => {
        const payload = await callList(DAILY_ROW_COUNT)

        expect(rowLines(payload.content[0]!.text)).toHaveLength(DAILY_ROW_COUNT)
        expect(modelVisibleTokens(payload)).toBeLessThan(DAILY_TOKEN_BUDGET)
    })

    it('still hands the UI app every field of every row', async () => {
        const payload = await callList(3, { limit: 3 })
        const appData = payload._meta?.[APP_DATA_META_KEY] as { results: Record<string, unknown>[] }

        expect(appData.results).toHaveLength(3)
        expect(appData.results[0]!.scanner_snapshot).toEqual(createScannerSnapshot())
    })

    it('returns every field to a caller that asks for JSON', async () => {
        const payload = await callList(3, { limit: 3, output_format: 'json' })

        expect(payload.content[0]!.text).toContain('Watch the checkout step.')
        expect(payload.structuredContent).not.toBeUndefined()
    })
})
