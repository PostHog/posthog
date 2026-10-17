import { type DeepLinkKind, deepLinkKind } from './deepLinkKind'

describe('deepLinkKind', () => {
    test.each<[string, DeepLinkKind | null]>([
        ['posthog://', null],
        ['posthog:///', null],
        ['posthog-dev:///?foo=1', null],
        ['posthog://report/0192-abc', 'report'],
        ['posthog:///report/0192-abc', 'report'],
        ['posthog-preview://views/insight/aBc123', 'views'],
        ['/sign-in', 'sign_in'],
        ['posthog://callback?code=secret&state=x', 'callback'],
        ['https://us.posthog.com/inbox', 'inbox'],
        ['https://us.posthog.com/', null],
        ['posthog://project/2/insights', 'other'],
    ])('%s', (path, expected) => {
        expect(deepLinkKind(path)).toBe(expected)
    })
})
