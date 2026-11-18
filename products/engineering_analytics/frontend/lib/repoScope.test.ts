import type { GitHubSourceApi } from '../generated/api.schemas'
import { pickForwardRepo, repoFromPath, switchRepoPath } from './repoScope'

const SOURCES: GitHubSourceApi[] = [
    { id: 'src-a', repo: 'PostHog/posthog', prefix: 'a', synced: true },
    { id: 'src-b', repo: 'PostHog/posthog-js', prefix: 'b', synced: true },
    { id: 'src-c', repo: '', prefix: 'legacy', synced: true },
]

describe('repoScope', () => {
    it.each([
        ['a tab stays on that tab', '/engineering-analytics/repos/PostHog/posthog/workflows', '/workflows'],
        [
            'a team page stays on that team',
            '/engineering-analytics/repos/PostHog/posthog/teams/team-cdp',
            '/teams/team-cdp',
        ],
        [
            'a pull request lands on the pull request list',
            '/engineering-analytics/repos/PostHog/posthog/pull-requests/42',
            '/pull-requests',
        ],
        [
            'a CI explorer lands on the pull request list',
            '/engineering-analytics/repos/PostHog/posthog/pull-requests/42/ci-explorer',
            '/pull-requests',
        ],
        [
            'a workflow run lands on the workflows tab',
            '/engineering-analytics/repos/PostHog/posthog/actions/runs/7',
            '/workflows',
        ],
        ['a repo-less tab keeps its tab', '/engineering-analytics/tests', '/tests'],
    ])('switching repository from %s', (_label, pathname, rest) => {
        expect(switchRepoPath(pathname, 'PostHog/posthog-js')).toBe(
            `/engineering-analytics/repos/PostHog/posthog-js${rest}`
        )
    })

    it.each([
        [
            'the requested repository, matched case-insensitively',
            { repo: 'posthog/POSTHOG-JS' },
            'PostHog/posthog',
            'PostHog/posthog-js',
        ],
        ['the last repository used over the default', {}, 'PostHog/posthog-js', 'PostHog/posthog-js'],
        ['the default when the last one is gone', {}, 'PostHog/gone', 'PostHog/posthog'],
        ['the default when the requested one is unknown', { repo: 'PostHog/unknown' }, null, 'PostHog/posthog'],
        ['nothing for a legacy source that names no repository', { sourceId: 'src-c' }, 'PostHog/posthog-js', null],
    ])('forwarding picks %s', (_label, requested, lastRepo, expected) => {
        expect(pickForwardRepo(SOURCES, requested, lastRepo)).toBe(expected)
    })

    it.each([
        ['an encoded segment', '/engineering-analytics/repos/PostHog/posthog%2Ejs/overview', 'PostHog/posthog.js'],
        ['a malformed escape, kept raw', '/engineering-analytics/repos/%zz/posthog/overview', '%zz/posthog'],
    ])('reads the repository from %s', (_label, pathname, expected) => {
        expect(repoFromPath(pathname)).toBe(expected)
    })

    it('has nothing to forward to when no source names a repository', () => {
        expect(pickForwardRepo([SOURCES[2]], {}, null)).toBeNull()
    })
})
