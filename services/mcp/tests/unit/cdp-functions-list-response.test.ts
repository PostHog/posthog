import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS as CDP_TOOLS } from '@/tools/generated/cdp_functions'
import type { Context } from '@/tools/types'

// The list response echoes each function's `filters`. The compiled `filters.bytecode`
// (up to ~2.4k elements per row) is redundant with the human-readable events/actions/
// properties and, across a full page, overflows the tool exec token cap. The list must
// select only the human-readable filter subfields; the full config stays on
// cdp-functions-retrieve.

function createMockContext(results: unknown[]): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue({ count: results.length, results }),
            getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/1'),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('1'),
            getOrgID: vi.fn(),
            getRegion: vi.fn().mockResolvedValue('us'),
        },
        env: { POSTHOG_BASE_URL: 'https://us.posthog.com' },
        sessionManager: {},
        cache: {},
        getDistinctId: async () => 'test',
    } as unknown as Context
}

describe('cdp-functions-list response shaping', () => {
    it('drops the compiled filters.bytecode but keeps the human-readable filter expression', async () => {
        const context = createMockContext([
            {
                id: 'abc',
                name: 'My destination',
                type: 'destination',
                filters: {
                    source: 'events',
                    events: [{ id: '$pageview', name: '$pageview', type: 'events' }],
                    actions: [],
                    properties: [{ key: 'browser', value: 'Chrome' }],
                    filter_test_accounts: true,
                    bytecode: ['_H', 1, 32, 'a', 32, 'b'],
                    transpiled: 'function () { return true }',
                    bytecode_error: null,
                },
            },
        ])
        const tool = CDP_TOOLS['cdp-functions-list']!()

        // Handlers return the plain JSON object directly; the MCP server wraps it later.
        const data = (await tool.handler(context, {})) as { results: { filters: Record<string, unknown> }[] }
        const filters = data.results[0]!.filters

        expect(filters.bytecode).toBeUndefined()
        expect(filters.transpiled).toBeUndefined()
        expect(filters.bytecode_error).toBeUndefined()
        expect(filters.events).toEqual([{ id: '$pageview', name: '$pageview', type: 'events' }])
        expect(filters.properties).toEqual([{ key: 'browser', value: 'Chrome' }])
        expect(filters.filter_test_accounts).toBe(true)
    })
})
