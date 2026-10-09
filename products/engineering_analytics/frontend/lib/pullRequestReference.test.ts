import type { GitHubSourceApi } from '../generated/api.schemas'
import {
    type PullRequestReference,
    type PullRequestTarget,
    parsePullRequestReference,
    resolvePullRequestTarget,
} from './pullRequestReference'

const LINK: PullRequestReference = { kind: 'link', owner: 'PostHog', repo: 'posthog', number: 123 }
const NUMBER: PullRequestReference = { kind: 'number', number: 123 }

const POSTHOG: GitHubSourceApi = { id: 'src-posthog', repo: 'PostHog/posthog', prefix: '', synced: true }
const WEBSITE: GitHubSourceApi = { id: 'src-website', repo: 'PostHog/posthog.com', prefix: '', synced: true }

describe('pullRequestReference', () => {
    it.each<[string, string, PullRequestReference | null]>([
        ['a link', 'https://github.com/PostHog/posthog/pull/123', LINK],
        ['a link with no scheme', 'github.com/PostHog/posthog/pull/123', LINK],
        ['a link with a www host in capitals', 'HTTP://WWW.GitHub.com/PostHog/posthog/pull/123', LINK],
        ['a link to the files tab', 'https://github.com/PostHog/posthog/pull/123/files', LINK],
        ['a link with a query', 'https://github.com/PostHog/posthog/pull/123?diff=split', LINK],
        ['a link to a review comment', 'https://github.com/PostHog/posthog/pull/123#discussion_r42', LINK],
        ['a link inside other text', 'see https://github.com/PostHog/posthog/pull/123, please', LINK],
        [
            'a link to a repository with a dot in its name',
            'https://github.com/PostHog/posthog.com/pull/7',
            { kind: 'link', owner: 'PostHog', repo: 'posthog.com', number: 7 },
        ],
        ['owner/repo#n', 'PostHog/posthog#123', { ...LINK, kind: 'repo_number' }],
        ['#n', '#123', NUMBER],
        ['digits', '123', NUMBER],
        ['digits in whitespace', '  123\n', NUMBER],
        ['a link on another host', 'https://gitlab.com/PostHog/posthog/pull/123', null],
        ['a host that only ends in github.com', 'https://notgithub.com/PostHog/posthog/pull/123', null],
        ['a GitHub address in the path of another site', 'https://example.com/github.com/a/b/pull/123', null],
        ['an issue link', 'https://github.com/PostHog/posthog/issues/123', null],
        ['a commit link', 'https://github.com/PostHog/posthog/commit/123', null],
        ['a link to pull request zero', 'https://github.com/PostHog/posthog/pull/0', null],
        ['zero', '#0', null],
        ['digits with a suffix', '123abc', null],
        ['words', 'not a pr', null],
        ['nothing', '   ', null],
    ])('parses %s', (_label, text, expected) => {
        expect(parsePullRequestReference(text)).toEqual(expected)
    })

    it.each<[string, PullRequestReference, GitHubSourceApi[], GitHubSourceApi | null, PullRequestTarget | null]>([
        [
            'a bare number to the picked repository',
            NUMBER,
            [POSTHOG, WEBSITE],
            WEBSITE,
            { owner: 'PostHog', repo: 'posthog.com', number: 123, sourceId: 'src-website' },
        ],
        [
            'a bare number to the only connected repository',
            NUMBER,
            [POSTHOG],
            null,
            { owner: 'PostHog', repo: 'posthog', number: 123, sourceId: 'src-posthog' },
        ],
        ['a bare number to nothing when several repositories are connected', NUMBER, [POSTHOG, WEBSITE], null, null],
        [
            'a bare number to nothing when the only source reports no repository',
            NUMBER,
            [{ ...POSTHOG, repo: '' }],
            null,
            null,
        ],
        [
            'a link to its own repository, in the casing of the source, when another is picked',
            { kind: 'link', owner: 'posthog', repo: 'POSTHOG', number: 123 },
            [POSTHOG, WEBSITE],
            WEBSITE,
            { owner: 'PostHog', repo: 'posthog', number: 123, sourceId: 'src-posthog' },
        ],
        [
            'a link to a repository with no connected source as typed',
            { kind: 'link', owner: 'keajs', repo: 'kea', number: 123 },
            [POSTHOG],
            POSTHOG,
            { owner: 'keajs', repo: 'kea', number: 123, sourceId: null },
        ],
    ])('resolves %s', (_label, reference, sources, pickedSource, expected) => {
        expect(resolvePullRequestTarget(reference, sources, pickedSource)).toEqual(expected)
    })
})
