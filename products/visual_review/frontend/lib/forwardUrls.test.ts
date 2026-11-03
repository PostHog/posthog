import type { RepoApi } from '../generated/api.schemas'
import { ForwardUrl, LegacyRoute, legacyForwardUrl, pickLandingRepo } from './forwardUrls'

function makeRepo(id: string, repoFullName: string): RepoApi {
    return {
        id,
        team_id: 1,
        repo_external_id: 1,
        repo_full_name: repoFullName,
        baseline_file_paths: {},
        enable_pr_comments: true,
        debt_digest_enabled: false,
        created_at: '2026-01-01T00:00:00Z',
    }
}

describe('forwardUrls', () => {
    it.each<{
        name: string
        route: LegacyRoute
        search: Record<string, any>
        hash: Record<string, any>
        expected: ForwardUrl
    }>([
        {
            name: 'a repo page keeps its filters',
            route: { kind: 'repoPage', repoId: 'uuid', page: 'flakiness' },
            search: {},
            hash: { preset: 'broken' },
            expected: {
                path: '/visual-review/repos/PostHog/posthog/flakiness',
                searchParams: {},
                hashParams: { preset: 'broken' },
            },
        },
        {
            name: 'a snapshot history page encodes its segments',
            route: { kind: 'snapshotHistory', repoId: 'uuid', runType: 'storybook', identifier: 'scenes/app--light' },
            search: {},
            hash: {},
            expected: {
                path: '/visual-review/repos/PostHog/posthog/storybook/snapshots/scenes%2Fapp--light',
                searchParams: {},
                hashParams: {},
            },
        },
        {
            name: 'an old PR comment link moves the snapshot into the hash',
            route: { kind: 'run', runId: 'run-1' },
            search: { snapshot: 'snap-1', utm_source: 'github' },
            hash: {},
            expected: {
                path: '/visual-review/repos/PostHog/posthog/runs/run-1',
                searchParams: { utm_source: 'github' },
                hashParams: { snapshot: 'snap-1' },
            },
        },
        {
            name: 'a run link that already selects in the hash keeps it',
            route: { kind: 'run', runId: 'run-1' },
            search: {},
            hash: { snapshot: 'snap-2' },
            expected: {
                path: '/visual-review/repos/PostHog/posthog/runs/run-1',
                searchParams: {},
                hashParams: { snapshot: 'snap-2' },
            },
        },
    ])('legacyForwardUrl: $name', ({ route, search, hash, expected }) => {
        expect(legacyForwardUrl(route, 'PostHog/posthog', search, hash)).toEqual(expected)
    })

    const first = makeRepo('first', 'PostHog/posthog')
    const second = makeRepo('second', 'PostHog/posthog.com')

    it.each([
        { name: 'opens the repo used last', repos: [first, second], last: 'posthog/POSTHOG.com', expected: 'second' },
        {
            name: 'falls back to the first repo when the last one is gone',
            repos: [first],
            last: 'PostHog/gone',
            expected: 'first',
        },
        { name: 'falls back to the first repo with no history', repos: [first, second], last: null, expected: 'first' },
        { name: 'returns null with no repos', repos: [], last: 'PostHog/posthog', expected: null },
    ])('pickLandingRepo: $name', ({ repos, last, expected }) => {
        expect(pickLandingRepo(repos, last)?.id ?? null).toBe(expected)
    })
})
