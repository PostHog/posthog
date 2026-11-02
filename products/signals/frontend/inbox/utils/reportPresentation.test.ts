import { deriveHeadline, parsePrUrlParts } from './reportPresentation'

describe('deriveHeadline', () => {
    it('shows a markdown link label without its syntax or URL', () => {
        expect(
            deriveHeadline(
                'Account: [Example workspace](https://example.com/accounts/example) | 12 active users need review. More detail follows.'
            )
        ).toBe('Account: Example workspace | 12 active users need review.')
    })

    it('does not parse markdown links beyond the headline input limit', () => {
        const oversizedLabel = 'a'.repeat(1_000)

        expect(deriveHeadline(`[${oversizedLabel}](https://example.com)`)).toBe(`${'[' + 'a'.repeat(139)}…`)
    })
})

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
