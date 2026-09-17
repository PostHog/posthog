import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS as CDP_TOOLS } from '@/tools/generated/cdp_functions'
import { GENERATED_TOOLS as MESSAGING_TOOLS } from '@/tools/generated/messaging'
import { GENERATED_TOOLS as PLATFORM_TOOLS } from '@/tools/generated/platform_features'
import { withPageOffsets } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'

describe('withPageOffsets', () => {
    it.each([
        [
            'an absolute link built from a cluster-internal host',
            'http://posthog-api.internal:8000/api/projects/1/conversations/tickets/?limit=50&offset=100',
            100,
        ],
        ['a relative link', '/api/projects/1/conversations/tickets/?limit=50&offset=50', 50],
        ['a link without an offset param', 'https://us.posthog.com/api/projects/1/persons/', null],
        ['no link', null, null],
    ])('reads the next offset from %s', (_case, link, expected) => {
        expect(withPageOffsets({ count: 200, next: link, previous: null, results: [] })).toEqual({
            count: 200,
            next_offset: expected,
            previous_offset: null,
            results: [],
        })
    })

    it('reads a previous link without an offset param as the first page', () => {
        const envelope = withPageOffsets({
            count: 200,
            next: null,
            previous: 'http://posthog-api.internal:8000/api/projects/1/persons/?limit=50',
            results: [],
        })

        expect(envelope.previous_offset).toBe(0)
    })

    it('leaves a response that is not an envelope alone', () => {
        expect(withPageOffsets([{ id: 'one' }])).toEqual([{ id: 'one' }])
    })
})

describe('pagination shaping in generated handlers', () => {
    function createMockContext(envelope: unknown): Context {
        return {
            api: {
                request: vi.fn().mockResolvedValue(envelope),
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

    // Every paginated endpoint shares one envelope type, so shaping by response type alone reached
    // endpoints that page by cursor or by page number. Their token lives only in the link, and
    // deleting it left the agent with `next_offset: null` on a page that still had data behind it.
    it.each([
        ['comments-list', PLATFORM_TOOLS, 'cursor=cD0yMDI2LTA5LTE2VDAwOjAwOjAwWg'],
        ['opt-outs-list', MESSAGING_TOOLS, 'page=2'],
    ])('%s keeps the link that carries its paging token', async (name, tools, token) => {
        const next = `https://us.posthog.com/api/projects/1/${name}/?${token}`
        const context = createMockContext({ count: 200, next, previous: null, results: [] })

        const result = (await tools[name]!().handler(context, {})) as Record<string, unknown>

        expect(result.next).toBe(next)
        expect(result).not.toHaveProperty('next_offset')
    })

    it('cdp-functions-list still reports the offset to send for the next page', async () => {
        const context = createMockContext({
            count: 200,
            next: 'http://posthog-api.internal:8000/api/projects/1/hog_functions/?limit=100&offset=100',
            previous: null,
            results: [],
        })

        const result = (await CDP_TOOLS['cdp-functions-list']!().handler(context, {})) as Record<string, unknown>

        expect(result.next_offset).toBe(100)
        expect(result).not.toHaveProperty('next')
    })
})
