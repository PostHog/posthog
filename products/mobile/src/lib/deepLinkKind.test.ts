import { type DeepLinkKind, deepLinkKind, webLinkTarget } from './deepLinkKind'

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
        ['https://us.posthog.com/project/2/error_tracking/0192-abc', 'error_tracking'],
        ['https://eu.posthog.com/project/2/replay/0192-abc?t=42', 'replay'],
        ['posthog://errors/0192-abc', 'error_tracking'],
        ['https://us.posthog.com/project/2/views', 'other'],
    ])('%s', (path, expected) => {
        expect(deepLinkKind(path)).toBe(expected)
    })

    test.each<[string, string | null]>([
        ['https://us.posthog.com/project/2/error_tracking/0192-abc?fingerprint=x', '/errors/0192-abc?from=link'],
        ['https://us.posthog.com/project/2/error-tracking/0192-abc', '/errors/0192-abc?from=link'],
        ['https://us.posthog.com/project/2/error_tracking/configuration', null],
        ['https://us.posthog.com/project/2/replay/0192-abc?t=42', '/replay/0192-abc?source=link&t=42'],
        [
            'https://us.posthog.com/project/2/replay/home?sessionRecordingId=0192-abc&t=7',
            '/replay/0192-abc?source=link&t=7',
        ],
        ['https://us.posthog.com/project/2/replay/0192-abc?timestamp=1700000000000', '/replay/0192-abc?source=link'],
        ['https://us.posthog.com/project/2/replay/playlists/abc', null],
        ['https://us.posthog.com/project/2/insights/abc', null],
        ['posthog://replay/0192-abc?from=push', null],
    ])('opens %s in the app at %s', (path, expected) => {
        expect(webLinkTarget(path)).toBe(expected)
    })
})
