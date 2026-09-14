import { describe, expect, it, vi } from 'vitest'

import { estimateTokens } from '@/lib/estimate-tokens'
import { formatResponse } from '@/lib/response'
import { GENERATED_TOOLS } from '@/tools/generated/replay'
import type { Context } from '@/tools/types'

/**
 * A page of playlists is how an agent discovers which playlist to open, so it has to cost
 * much less than the detail calls that follow it. The same page unshaped costs over ten times
 * this, because each playlist repeats its whole filter configuration.
 */
const TOKEN_BUDGET = 2_000

const PAGE_SIZE = 10

const SESSION_ID_COUNT = 140

/** The `UserBasic` keys an agent cannot act on. Email stays. */
const STRIPPED_USER_FIELDS = ['uuid', 'distinct_id', 'first_name', 'last_name', 'is_email_verified', 'hedgehog_config']

function createUser(id: number, firstName: string): Record<string, unknown> {
    return {
        id,
        uuid: `00000000-0000-4000-8000-0000000000${id}`,
        distinct_id: `distinct-id-for-user-${id}`,
        first_name: firstName,
        last_name: 'Lovelace',
        email: `${firstName.toLowerCase()}@example.com`,
        is_email_verified: true,
        hedgehog_config: {
            use_as_profile: false,
            color: 'invert-hue',
            accessories: ['flag', 'sunglasses', 'parrot'],
            skin: 'default',
        },
        role_at_organization: null,
    }
}

/** A saved filter pinned to specific recordings keeps one session ID per recording in its filters. */
function createPlaylist(index: number): Record<string, unknown> {
    return {
        id: 1000 + index,
        short_id: `plist${index}`,
        name: `Onboarding drop-offs ${index}`,
        derived_name: null,
        description: `Recordings collected while reviewing onboarding step ${index}.`,
        pinned: index === 0,
        created_at: '2026-02-18T18:28:34.858807Z',
        created_by: createUser(1, 'Ada'),
        deleted: false,
        filters: {
            date_from: '-30d',
            date_to: null,
            duration: [{ key: 'active_seconds', type: 'recording', value: 5, operator: 'gt' }],
            filter_group: { type: 'AND', values: [{ type: 'AND', values: [] }] },
            filter_test_accounts: false,
            order: 'start_time',
            session_ids: Array.from(
                { length: SESSION_ID_COUNT },
                (_, i) => `01960000-0000-7000-8000-${String(index).padStart(4, '0')}${String(i).padStart(8, '0')}`
            ),
        },
        last_modified_at: '2026-06-19T07:10:12.181366Z',
        last_modified_by: createUser(2, 'Grace'),
        recordings_counts: {
            saved_filters: {
                count: SESSION_ID_COUNT,
                watched_count: 3,
                has_more: false,
                increased: false,
                last_refreshed_at: '2026-06-19T07:12:00.000000Z',
            },
            collection: { count: null, watched_count: null },
        },
        type: 'filters',
        is_synthetic: false,
    }
}

function createMockContext(result: Record<string, unknown>): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue(result),
            getProjectBaseUrl: () => 'https://us.posthog.com/project/7',
        },
        stateManager: { getProjectId: async () => 7 },
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
}

describe('session-recording-playlists-list response budget', () => {
    const tool = GENERATED_TOOLS['session-recording-playlists-list']!()

    async function listPlaylists(): Promise<Record<string, unknown>> {
        const page = {
            count: PAGE_SIZE,
            next: null,
            previous: null,
            results: Array.from({ length: PAGE_SIZE }, (_, index) => createPlaylist(index)),
        }
        return (await tool.handler(createMockContext(page), {})) as unknown as Record<string, unknown>
    }

    it(`keeps a page of ${PAGE_SIZE} playlists within the response budget`, async () => {
        const shaped = await listPlaylists()

        expect(estimateTokens(formatResponse(shaped))).toBeLessThan(TOKEN_BUDGET)
    })

    it('drops the filters, session IDs and creator metadata a row cannot act on', async () => {
        const shaped = await listPlaylists()
        const rows = shaped.results as Record<string, unknown>[]

        expect(JSON.stringify(shaped)).not.toContain('01960000-0000-7000-8000-')
        for (const row of rows) {
            expect(row).not.toHaveProperty('filters')
            expect(row).not.toHaveProperty('description')
            expect(row).not.toHaveProperty('last_modified_by')
            const creator = row.created_by as Record<string, unknown>
            expect(creator.email).toBe('ada@example.com')
            for (const field of STRIPPED_USER_FIELDS) {
                expect(creator).not.toHaveProperty(field)
            }
        }
    })

    it('keeps the metadata an agent picks a playlist by', async () => {
        const shaped = await listPlaylists()
        const rows = shaped.results as Record<string, unknown>[]

        expect(rows).toHaveLength(PAGE_SIZE)
        expect(rows[0]).toMatchObject({
            short_id: 'plist0',
            name: 'Onboarding drop-offs 0',
            type: 'filters',
            pinned: true,
            is_synthetic: false,
            created_at: '2026-02-18T18:28:34.858807Z',
            last_modified_at: '2026-06-19T07:10:12.181366Z',
        })
        expect((rows[0]!.recordings_counts as { saved_filters: { count: number } }).saved_filters.count).toBe(
            SESSION_ID_COUNT
        )
    })
})
