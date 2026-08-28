import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/visual_review'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

// The flakiness endpoint answers with an envelope, not a bare list, so the response
// filter runs once over the whole body. An allowlist written in entry-level paths
// matches nothing there and the tool returns an empty object on every call.
const ENVELOPE = {
    entries: [
        {
            identifier: 'scenes-app-flakiness--unstable--dark',
            run_type: 'storybook',
            flakiness_state: 'unstable',
            hard_rate: 0.42,
            quarantine: { reason: 'renders a scrolled timeline', expires_at: null, created_at: '2026-08-01T00:00:00Z' },
            // Outside the allowlist: a data URL and two 30-day series the page's strip
            // needs and an agent does not. These are the reason the allowlist exists.
            thumbnail: 'data:image/png;base64,AAAA',
            hard_series: [0, 1, 0, 1],
        },
    ],
    totals: { broken: 1, unstable: 2, clean: 3, listed: 1 },
    truncated: false,
    generated_at: '2026-08-26T00:00:00Z',
}

function mockContext(): Context {
    return {
        stateManager: { getProjectId: async () => 1 },
        api: {
            getProjectBaseUrl: () => 'https://us.posthog.com/project/1',
            request: async () => ENVELOPE,
        },
    } as unknown as Context
}

describe('visual-review-repos-flakiness-retrieve response filtering', () => {
    const tool = GENERATED_TOOLS['visual-review-repos-flakiness-retrieve'] as () => ToolBase<ZodObjectAny>

    async function call(params: Record<string, unknown>): Promise<any> {
        const result: any = await tool().handler(mockContext(), { id: 'repo-uuid', ...params })
        return result.data ?? result
    }

    it('keeps the entries and the envelope when `fields` is omitted', async () => {
        const result = await call({})

        expect(result.entries).toHaveLength(1)
        expect(result.entries[0].identifier).toBe('scenes-app-flakiness--unstable--dark')
        expect(result.entries[0].quarantine.reason).toBe('renders a scrolled timeline')
        expect(result.totals.broken).toBe(1)
        expect(result.generated_at).toBe('2026-08-26T00:00:00Z')
    })

    it('drops the thumbnail and the strip series that only the page needs', async () => {
        const result = await call({})

        expect(result.entries[0]).not.toHaveProperty('thumbnail')
        expect(result.entries[0]).not.toHaveProperty('hard_series')
    })

    it('narrows the entries when `fields` is passed', async () => {
        const result = await call({ fields: ['entries.*.identifier', 'entries.*.flakiness_state'] })

        expect(result.entries[0]).toEqual({
            identifier: 'scenes-app-flakiness--unstable--dark',
            flakiness_state: 'unstable',
        })
        expect(result).not.toHaveProperty('totals')
    })
})
