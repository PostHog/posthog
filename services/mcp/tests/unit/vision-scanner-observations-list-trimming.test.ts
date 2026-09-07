import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/replay_vision'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

// One observation row carrying every field the tool's `response.exclude` drops, alongside the
// siblings it must keep, so a broken path (silent no-op -> full payload back) is visible.
const FULL_ROW = {
    id: 'obs-1',
    session_id: 'sess-1',
    status: 'succeeded',
    scanner_snapshot: {
        name: 'Checkout drop-offs',
        scanner_type: 'monitor',
        scanner_version: 3,
        // Identical on every row of a scanner's page, and the largest field on it.
        scanner_config: { prompt: 'Did the shopper abandon the cart?', allow_inconclusive: true },
        query: { kind: 'RecordingsQuery', events: [{ id: '$pageview' }] },
    },
    scanner_result: {
        model_output: {
            scanner_type: 'monitor',
            verdict: 'yes',
            reasoning: 'The shopper opened the cart and left without paying.',
            // Restates `reasoning` interleaved with timestamp chips.
            reasoning_segments: [
                { kind: 'text', value: 'The shopper opened the cart and left without paying.' },
                { kind: 'chip', timestamp_ms: 42000 },
            ],
        },
        signals_count: 0,
    },
}

// A summarizer row: same duplication, under `summary_segments`, because segments are written as
// `{citation_field}_segments` and summarizer cites `summary` rather than `reasoning`.
const SUMMARIZER_ROW = {
    id: 'obs-2',
    session_id: 'sess-2',
    status: 'succeeded',
    scanner_snapshot: {
        name: 'Session summaries',
        scanner_type: 'summarizer',
        scanner_version: 1,
        scanner_config: { prompt: 'Summarize what the person did.', length: 'long' },
        query: { kind: 'RecordingsQuery', events: [{ id: '$pageview' }] },
    },
    scanner_result: {
        model_output: {
            scanner_type: 'summarizer',
            title: 'Renamed a project, then opened billing',
            summary: 'The person renamed a project and then opened the billing page.',
            summary_segments: [
                { kind: 'text', value: 'The person renamed a project and then opened the billing page.' },
                { kind: 'chip', timestamp_ms: 91000 },
            ],
        },
        signals_count: 0,
    },
}

function mockContext(row: object = FULL_ROW): Context {
    return {
        stateManager: { getProjectId: async () => 1 },
        api: {
            getProjectBaseUrl: () => 'https://us.posthog.com/project/1',
            request: async () => ({ count: 1, next: null, previous: null, results: [structuredClone(row)] }),
        },
    } as unknown as Context
}

describe('vision-scanners-observations-list row trimming', () => {
    const listTool = GENERATED_TOOLS['vision-scanners-observations-list'] as () => ToolBase<ZodObjectAny>

    it('drops the repeated snapshot fields and the duplicated reasoning segments', async () => {
        const result: any = await listTool().handler(mockContext(), { scanner_id: 'scanner-1' })
        const [row] = result.results

        expect(row.scanner_snapshot.scanner_config).not.toHaveProperty('prompt')
        expect(row.scanner_snapshot).not.toHaveProperty('query')
        expect(row.scanner_result.model_output).not.toHaveProperty('reasoning_segments')
    })

    it('keeps the per-row output a caller reads, and the version tag beside it', async () => {
        const result: any = await listTool().handler(mockContext(), { scanner_id: 'scanner-1' })
        const [row] = result.results

        expect(row.scanner_result.model_output.reasoning).toBe('The shopper opened the cart and left without paying.')
        expect(row.scanner_result.model_output.verdict).toBe('yes')
        expect(row.scanner_snapshot.scanner_version).toBe(3)
        // Trimming one config key must not take the rest of the config with it.
        expect(row.scanner_snapshot.scanner_config.allow_inconclusive).toBe(true)
        // Enrichment runs on the trimmed rows, so each row still deep-links its recording.
        expect(row._posthogUrl).toBe('https://us.posthog.com/project/1/replay/sess-1')
    })

    it('drops the duplicated summary segments on a summarizer row, and keeps the summary', async () => {
        const result: any = await listTool().handler(mockContext(SUMMARIZER_ROW), { scanner_id: 'scanner-2' })
        const [row] = result.results

        expect(row.scanner_result.model_output).not.toHaveProperty('summary_segments')
        expect(row.scanner_result.model_output.summary).toBe(
            'The person renamed a project and then opened the billing page.'
        )
    })

    it('defaults to a page a caller can read without naming a limit', () => {
        expect(listTool().schema.parse({ scanner_id: 'scanner-1' }).limit).toBe(20)
    })
})
