import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/web_analytics'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

const WRAPPERS = ['query-web-overview', 'query-web-stats', 'query-web-vitals'] as const

function createContext(): { context: Context; runQuery: ReturnType<typeof vi.fn> } {
    const runQuery = vi.fn().mockResolvedValue({ results: [] })
    const context = {
        api: {
            query: vi.fn().mockReturnValue({ runQuery }),
            getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('1'),
            getCachedOrFetchProject: vi.fn().mockResolvedValue({ test_account_filters_default_checked: false }),
        },
    } as unknown as Context
    return { context, runQuery }
}

async function postedQuery(toolName: string, params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const { context, runQuery } = createContext()
    await GENERATED_TOOLS[toolName]!().handler(context, params as never)
    return runQuery.mock.calls[0]![0].query as Record<string, unknown>
}

function jsonExamples(description: string): Record<string, unknown>[] {
    return [...description.matchAll(/```json\n([\s\S]*?)\n```/g)].map(
        (match) => JSON.parse(match[1]!) as Record<string, unknown>
    )
}

describe('web analytics query wrappers', () => {
    it.each(WRAPPERS)('%s runs with no inputs at all', async (toolName) => {
        const query = await postedQuery(toolName, {})

        expect(query.kind).toBeTruthy()
    })

    it('query-web-stats breaks down by page when breakdownBy is omitted', async () => {
        expect(await postedQuery('query-web-stats', {})).toMatchObject({ breakdownBy: 'Page' })
    })

    it('query-web-vitals reads LCP at p75 when metric and percentile are omitted', async () => {
        expect(await postedQuery('query-web-vitals', {})).toMatchObject({ metric: 'LCP', percentile: 'p75' })
    })

    it.each([
        ['LCP', [2500, 4000]],
        ['INP', [200, 500]],
        ['CLS', [0.1, 0.25]],
        ['FCP', [1800, 3000]],
    ] as const)('query-web-vitals bands %s against the standard thresholds', async (metric, thresholds) => {
        expect(await postedQuery('query-web-vitals', { metric })).toMatchObject({ thresholds })
    })

    it('query-web-vitals keeps thresholds the caller supplied', async () => {
        const query = await postedQuery('query-web-vitals', { metric: 'LCP', thresholds: [1000, 2000] })

        expect(query.thresholds).toEqual([1000, 2000])
    })

    describe.each(WRAPPERS)('%s description', (toolName) => {
        const examples = jsonExamples(getToolDefinition(toolName).description)

        it('carries at least one example', () => {
            expect(examples.length).toBeGreaterThan(0)
        })

        it.each(examples.map((example, index) => [index, example]))(
            'example %i passes the live schema',
            (_index, example) => {
                const parsed = GENERATED_TOOLS[toolName]!().schema.safeParse(example)

                expect(parsed.error?.issues ?? []).toEqual([])
            }
        )
    })
})
