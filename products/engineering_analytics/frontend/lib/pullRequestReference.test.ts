import {
    type PullRequestReference,
    type PullRequestTarget,
    parsePullRequestReference,
    resolvePullRequestTarget,
} from './pullRequestReference'

const LINK: PullRequestReference = { kind: 'link', owner: 'PostHog', repo: 'posthog', number: 123 }
const NUMBER: PullRequestReference = { kind: 'number', number: 123 }

describe('pullRequestReference', () => {
    it.each<[string, string, PullRequestReference | null]>([
        ['a link', 'https://github.com/PostHog/posthog/pull/123', LINK],
        ['a link with no scheme', 'github.com/PostHog/posthog/pull/123', LINK],
        ['a link with a www host in capitals', 'HTTP://WWW.GitHub.com/PostHog/posthog/pull/123', LINK],
        ['a link to the files tab', 'https://github.com/PostHog/posthog/pull/123/files', LINK],
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
        ['a host that only ends in github.com', 'https://notgithub.com/PostHog/posthog/pull/123', null],
        ['a GitHub address in the path of another site', 'https://example.com/github.com/a/b/pull/123', null],
        ['an issue link', 'https://github.com/PostHog/posthog/issues/123', null],
        ['a link to pull request zero', 'https://github.com/PostHog/posthog/pull/0', null],
        ['a link whose repository is a dot segment', 'https://github.com/PostHog/../pull/5', null],
        ['owner/repo#n whose repository is a dot segment', 'PostHog/..#5', null],
        ['zero', '#0', null],
        ['digits with a suffix', '123abc', null],
        ['words', 'not a pr', null],
        ['nothing', '   ', null],
    ])('parses %s', (_label, text, expected) => {
        expect(parsePullRequestReference(text)).toEqual(expected)
    })

    it.each<[string, PullRequestReference, string | null, PullRequestTarget | null]>([
        [
            'a bare number to the repository in scope',
            NUMBER,
            'PostHog/posthog.com',
            { owner: 'PostHog', repo: 'posthog.com', number: 123, inScope: true },
        ],
        ['a bare number to nothing when no repository is in scope', NUMBER, null, null],
        [
            'a link to the repository in scope, in the casing of the scope',
            { kind: 'link', owner: 'posthog', repo: 'POSTHOG', number: 123 },
            'PostHog/posthog',
            { owner: 'PostHog', repo: 'posthog', number: 123, inScope: true },
        ],
        [
            'a link to another repository as typed, out of scope',
            { kind: 'link', owner: 'keajs', repo: 'kea', number: 123 },
            'PostHog/posthog',
            { owner: 'keajs', repo: 'kea', number: 123, inScope: false },
        ],
        [
            'a link with no repository in scope as typed',
            LINK,
            null,
            { owner: 'PostHog', repo: 'posthog', number: 123, inScope: false },
        ],
    ])('resolves %s', (_label, reference, scopedRepo, expected) => {
        expect(resolvePullRequestTarget(reference, scopedRepo)).toEqual(expected)
    })
})
