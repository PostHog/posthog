import { genericSignalLink } from './signalLinks'

describe('genericSignalLink', () => {
    it.each([
        {
            name: 'links a PostHog entity from source_product + source_id before any URL on extra',
            signal: {
                source_product: 'error_tracking',
                source_id: 'issue-1',
                extra: { url: 'https://example.com/elsewhere' },
            },
            expected: { to: '/error_tracking/issue-1', label: 'View issue', external: false },
        },
        {
            name: 'links the logs scene without an entity id',
            signal: { source_product: 'logs', source_id: '', extra: {} },
            expected: { to: '/logs', label: 'View logs', external: false },
        },
        {
            name: 'prefers html_url over url on extra',
            signal: {
                source_product: 'github',
                source_id: '42',
                extra: {
                    url: 'https://api.github.com/repos/o/r/issues/42',
                    html_url: 'https://github.com/o/r/issues/42',
                },
            },
            expected: { to: 'https://github.com/o/r/issues/42', label: 'View in GitHub', external: true },
        },
        {
            name: 'humanizes a source product that has no filter option',
            signal: {
                source_product: 'sentry',
                source_id: 's-1',
                extra: { url: 'https://sentry.example.com/issues/1' },
            },
            expected: { to: 'https://sentry.example.com/issues/1', label: 'View in Sentry', external: true },
        },
        {
            name: 'ignores a relative path on extra',
            signal: { source_product: 'jira', source_id: 'J-1', extra: { url: '/browse/J-1' } },
            expected: null,
        },
        {
            name: 'returns null when nothing links',
            signal: { source_product: 'jira', source_id: 'J-1', extra: {} },
            expected: null,
        },
    ])('$name', ({ signal, expected }) => {
        expect(genericSignalLink(signal as any)).toEqual(expected)
    })
})
