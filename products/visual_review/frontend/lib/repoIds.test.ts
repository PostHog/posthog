import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { RepoApi } from '../generated/api.schemas'
import { RepoNotFoundError, clearRepoIdCache, findRepoByFullName, resolveRepoId } from './repoIds'

const REPOS_URL = '/api/projects/:team_id/visual_review/repos/'

function makeRepo(id: string, repoFullName: string, createdAt: string): RepoApi {
    return {
        id,
        team_id: 1,
        repo_external_id: 1,
        repo_full_name: repoFullName,
        baseline_file_paths: {},
        enable_pr_comments: true,
        debt_digest_enabled: false,
        created_at: createdAt,
    }
}

const older = makeRepo('older', 'PostHog/posthog', '2026-01-01T00:00:00Z')
const newer = makeRepo('newer', 'PostHog/posthog', '2026-03-01T00:00:00Z')
const other = makeRepo('other', 'PostHog/posthog.com', '2026-02-01T00:00:00Z')

describe('repoIds', () => {
    beforeEach(() => {
        initKeaTests()
        clearRepoIdCache()
    })

    it.each([
        { name: 'matches regardless of case', repos: [other, older], wanted: 'posthog/POSTHOG', expected: 'older' },
        {
            name: 'picks the newest of two rows with one name',
            repos: [newer, older],
            wanted: 'PostHog/posthog',
            expected: 'newer',
        },
        { name: 'returns null for an unknown name', repos: [older], wanted: 'PostHog/unknown', expected: null },
    ])('findRepoByFullName $name', ({ repos, wanted, expected }) => {
        expect(findRepoByFullName(repos, wanted)?.id ?? null).toBe(expected)
    })

    it('fetches the list again when a name is missing from the cached one', async () => {
        let listed = [older]
        let requests = 0
        useMocks({
            get: {
                [REPOS_URL]: () => {
                    requests += 1
                    return [200, { count: listed.length, next: null, previous: null, results: listed }]
                },
            },
        })

        expect(await resolveRepoId('1', 'PostHog/posthog')).toBe('older')
        listed = [older, other]
        expect(await resolveRepoId('1', 'PostHog/posthog.com')).toBe('other')
        expect(await resolveRepoId('1', 'PostHog/posthog.com')).toBe('other')
        expect(requests).toBe(2)

        await expect(resolveRepoId('1', 'PostHog/missing')).rejects.toBeInstanceOf(RepoNotFoundError)
        expect(requests).toBe(3)
    })

    it('shares one refresh between two lookups that miss at the same time', async () => {
        let listed = [older]
        let requests = 0
        useMocks({
            get: {
                [REPOS_URL]: () => {
                    requests += 1
                    return [200, { count: listed.length, next: null, previous: null, results: listed }]
                },
            },
        })

        await resolveRepoId('1', 'PostHog/posthog')
        listed = [older, other]
        const lookups = await Promise.all([
            resolveRepoId('1', 'PostHog/posthog.com'),
            resolveRepoId('1', 'PostHog/posthog.com'),
        ])
        expect(lookups).toEqual(['other', 'other'])
        expect(requests).toBe(2)
    })
})
