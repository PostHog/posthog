import { FileSystemEntry } from '~/queries/schema/schema-general'

import { railPreviewItems, railRecentItems, releaseRecentEntries } from './todayRailPreviewItems'

const flag = (ref: string, name: string, lastViewedAt: string): FileSystemEntry => ({
    id: `fs-${ref}`,
    path: `Unfiled/Feature flags/${name}`,
    type: 'feature_flag',
    ref,
    href: `/feature_flags/${ref}`,
    last_viewed_at: lastViewedAt,
})

const releaseVisit = (id: string, name: string, viewedAt: string): StoredVisit => ({
    type: 'release',
    id,
    name,
    href: `/releases/${id}`,
    viewedAt: Date.parse(viewedAt),
})

type StoredVisit = Parameters<typeof releaseRecentEntries>[1][number]

describe('the release rail card recents', () => {
    const sharedRecents = [
        flag('1', 'checkout-v2', '2026-09-28T12:00:00Z'),
        flag('2', 'new-onboarding', '2026-09-28T11:00:00Z'),
        flag('3', 'dark-mode', '2026-09-28T10:00:00Z'),
        { id: 'fs-r', path: 'Unfiled/Releases/Release', type: 'release', ref: 'r-old', href: '/releases/r-old' },
    ]

    test.each([
        [
            'a newer release visit ranks among the newest',
            '2026-09-28T13:00:00Z',
            ['checkout-v2', 'new-onboarding', 'Spring launch'],
        ],
        [
            'an older release visit stays out of the newest',
            '2026-09-28T09:00:00Z',
            ['checkout-v2', 'dark-mode', 'new-onboarding'],
        ],
    ])('%s', (_, viewedAt, expected) => {
        const entries = releaseRecentEntries(sharedRecents, [releaseVisit('r-1', 'Spring launch', viewedAt)])
        const rows = railRecentItems(railPreviewItems(entries, 'release'), [])

        expect(rows.map((row) => row.name)).toEqual(expected)
    })

    it('names a shared release from its stored visit and drops one it cannot name', () => {
        const entries = releaseRecentEntries(
            [
                { ...sharedRecents[3], ref: 'r-1', href: '/releases/r-1', last_viewed_at: '2026-09-28T14:00:00Z' },
                sharedRecents[3],
            ],
            [releaseVisit('r-1', 'Spring launch', '2026-09-28T08:00:00Z')]
        )

        expect(railPreviewItems(entries, 'release').map((row) => row.name)).toEqual(['Spring launch'])
    })
})
