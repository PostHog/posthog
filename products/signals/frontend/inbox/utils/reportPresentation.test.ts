import { parsePrUrlParts, pullRequestIdentity } from './reportPresentation'

describe('parsePrUrlParts', () => {
    it.each([
        ['https://github.com/PostHog/posthog/pull/00123/files?diff=split#discussion', 'posthog/posthog#123'],
        ['https://github.com/posthog/PostHog/pull/124', 'posthog/posthog#124'],
        ['https://github.com/PostHog/another/pull/123', 'posthog/another#123'],
    ])('identifies %s without losing the PR number', (url, expected) => {
        expect(pullRequestIdentity(url)).toBe(expected)
    })

    it('parses a canonical GitHub PR URL', () => {
        expect(parsePrUrlParts('https://github.com/PostHog/posthog/pull/123/files')).toEqual({
            owner: 'PostHog',
            repo: 'posthog',
            number: '123',
            repoSlug: 'PostHog/posthog',
        })
    })

    // `implementation_pr_url` is task-run output, so a PR-shaped path on any other host must not
    // become an "Open in GitHub" action.
    it.each([
        ['another host', 'https://evil.example/PostHog/posthog/pull/123'],
        ['a host that starts with github.com', 'https://github.com.evil.example/PostHog/posthog/pull/123'],
        ['plain http', 'http://github.com/PostHog/posthog/pull/123'],
        ['a GitHub path that is not a pull request', 'https://github.com/PostHog/posthog/issues/123'],
        ['a bare PR reference', 'PostHog/posthog#123'],
    ])('rejects %s', (_name, url) => {
        expect(parsePrUrlParts(url)).toBeNull()
        expect(pullRequestIdentity(url)).toBeNull()
    })
})
