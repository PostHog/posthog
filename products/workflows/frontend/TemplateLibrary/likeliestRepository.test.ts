import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import { BrandHints, likeliestRepository } from './likeliestRepository'

const NOW = Date.parse('2026-06-01T12:00:00Z')
const DAY_MS = 24 * 60 * 60 * 1000

function repository(name: string, overrides: Partial<GitHubRepoApi> = {}): GitHubRepoApi {
    return { id: name.length, name, full_name: `juniper/${name}`, ...overrides }
}

function daysAgo(days: number): string {
    return new Date(NOW - days * DAY_MS).toISOString()
}

const HINTS: BrandHints = {
    appUrls: ['https://app.juniper-studio.com', 'https://juniper-preview.vercel.app'],
    projectName: 'Juniper Studio',
    organizationName: 'Juniper Inc.',
}

describe('likeliestRepository', () => {
    it.each([
        [
            'a name match over a more recent push',
            [repository('billing', { pushed_at: daysAgo(0) }), repository('juniper-web', { pushed_at: daysAgo(30) })],
            'juniper/juniper-web',
        ],
        [
            'the name that matches more brand words',
            [repository('juniper-api'), repository('juniper-studio-site')],
            'juniper/juniper-studio-site',
        ],
        [
            'a name written as one word',
            [repository('mobile', { pushed_at: daysAgo(0) }), repository('juniperstudio', { pushed_at: daysAgo(20) })],
            'juniper/juniperstudio',
        ],
        [
            'the recent push among equal name matches',
            [
                repository('juniper-docs', { pushed_at: daysAgo(9) }),
                repository('juniper-www', { pushed_at: daysAgo(1) }),
            ],
            'juniper/juniper-www',
        ],
        [
            'a recent one-word name over a stale hyphenated one',
            [
                repository('juniper-studio-legacy', { pushed_at: daysAgo(900) }),
                repository('juniperstudio', { pushed_at: daysAgo(1) }),
            ],
            'juniper/juniperstudio',
        ],
        [
            'a live repository over an archived name match',
            [repository('juniper-studio', { archived: true }), repository('marketing', { pushed_at: daysAgo(2) })],
            'juniper/marketing',
        ],
        ['nothing without repositories', [], null],
    ])('picks %s', (_case, repositories, expected) => {
        expect(likeliestRepository(repositories, HINTS)?.full_name ?? null).toBe(expected)
    })

    it('keeps a joined name covering its words when another hint is that one word', () => {
        const hints = { appUrls: [], projectName: 'Juniper Studio', organizationName: 'juniperstudio' }
        const repositories = [
            repository('juniper-studio-legacy', { pushed_at: daysAgo(900) }),
            repository('juniperstudio', { pushed_at: daysAgo(1) }),
        ]

        expect(likeliestRepository(repositories, hints)?.full_name).toBe('juniper/juniperstudio')
    })

    it('ignores hosting domains and generic words when matching names', () => {
        const repositories = [
            repository('vercel-app-www', { pushed_at: daysAgo(5) }),
            repository('pricing', { pushed_at: daysAgo(1) }),
        ]

        expect(likeliestRepository(repositories, HINTS)?.full_name).toBe('juniper/pricing')
    })
})
