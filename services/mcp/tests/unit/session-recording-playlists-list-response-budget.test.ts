import { beforeAll, describe, expect, it } from 'vitest'

import { estimateTokens } from '@/lib/estimate-tokens'
import { GENERATED_TOOLS } from '@/tools/generated/replay'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type Context } from '@/tools/types'

/**
 * A page of playlists has to leave an agent enough context to act on the one it picked. The
 * ceiling is what keeps the list-to-detail flow usable, not the size the payload happens to be.
 */
const TOKEN_BUDGET = 3_000

const PAGE_SIZE = 10
const PINNED_SESSION_COUNT = 140

const AUTHOR = {
    id: 1,
    uuid: '00000000-0000-4000-8000-000000000001',
    distinct_id: 'distinct-id-for-the-author',
    first_name: 'Ada',
    last_name: 'Tester',
    email: 'ada@example.com',
    is_email_verified: true,
    hedgehog_config: { use_as_profile: false, color: 'invert-hue', accessories: ['flag'], skin: 'default' },
    role_at_organization: null,
}

const PINNED_SESSION_IDS = Array.from(
    { length: PINNED_SESSION_COUNT },
    (_, index) => `019a0000-0000-7000-8000-${String(index).padStart(12, '0')}`
)

function playlist(index: number): Record<string, unknown> {
    return {
        id: 3000 + index,
        short_id: `playlist${index}`,
        name: `Widget onboarding drop-off ${index}`,
        derived_name: null,
        description: 'Sessions where the person opened the widget and left before finishing setup.',
        pinned: false,
        created_at: '2026-06-18T18:28:34.858807Z',
        created_by: AUTHOR,
        deleted: false,
        filters: {
            order: 'start_time',
            date_to: null,
            date_from: '-30d',
            duration: [{ key: 'active_seconds', type: 'recording', value: 5, operator: 'gt' }],
            session_ids: PINNED_SESSION_IDS,
            filter_group: {
                type: 'AND',
                values: [
                    {
                        type: 'AND',
                        values: [{ key: '$current_url', type: 'event', value: '/widgets', operator: 'icontains' }],
                    },
                ],
            },
            order_direction: 'DESC',
            filter_test_accounts: true,
        },
        last_modified_at: '2026-06-19T07:10:12.181366Z',
        last_modified_by: AUTHOR,
        recordings_counts: {
            saved_filters: {
                count: PINNED_SESSION_COUNT,
                has_more: false,
                watched_count: 0,
                increased: false,
                last_refreshed_at: '2026-06-20T07:10:12.181366Z',
            },
            collection: { count: null, watched_count: 0 },
        },
        type: 'filters',
        is_synthetic: false,
    }
}

function mockContext(): Context {
    return {
        stateManager: { getProjectId: async () => 7 },
        api: {
            getProjectBaseUrl: () => 'https://us.posthog.com/project/7',
            request: async () => ({
                count: 219,
                next: 'https://us.posthog.com/api/projects/7/session_recording_playlists/?limit=10&offset=10',
                previous: null,
                results: Array.from({ length: PAGE_SIZE }, (_, index) => playlist(index)),
            }),
        },
    } as unknown as Context
}

describe('session-recording-playlists-list response budget', () => {
    let page: Record<string, unknown>
    let projection: string

    beforeAll(async () => {
        const tool = GENERATED_TOOLS['session-recording-playlists-list']!()
        page = (await tool.handler(mockContext(), { limit: PAGE_SIZE })) as unknown as Record<string, unknown>
        projection = page[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY] as string
    })

    it(`keeps a ${PAGE_SIZE}-playlist page within the response budget`, () => {
        expect(estimateTokens(projection)).toBeLessThan(TOKEN_BUDGET)
    })

    it('keeps what an agent picks a playlist by, and drops the pinned session IDs', () => {
        expect(projection).toContain('playlist0')
        expect(projection).toContain('Widget onboarding drop-off 0')
        expect(projection).toContain('left before finishing setup')
        expect(projection).toContain('$current_url')
        expect(projection).toContain(AUTHOR.email)

        expect(projection).not.toContain(PINNED_SESSION_IDS[0])
        expect(projection).not.toContain(AUTHOR.distinct_id)
        expect(projection).not.toContain('hedgehog_config')
    })

    it('leaves the structured payload whole for a caller that asks for every field', () => {
        const row = (page.results as Record<string, unknown>[])[0]!

        expect(row).toEqual(playlist(0))
    })
})
