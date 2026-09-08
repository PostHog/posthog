import { parsePrUrlParts } from './reportPresentation'

describe('parsePrUrlParts', () => {
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
    })
})
