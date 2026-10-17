import { validateHost } from './regions'

describe('validateHost', () => {
    test.each([
        ['us.posthog.com', 'https://us.posthog.com'],
        ['https://posthog.example.com/project/2/', 'https://posthog.example.com'],
        ['http://localhost:8010', 'http://localhost:8010'],
        ['http://127.0.0.1:8000', 'http://127.0.0.1:8000'],
        ['http://[::1]:8010', 'http://[::1]:8010'],
    ])('accepts %s as %s', (input, host) => {
        expect(validateHost(input)).toEqual({ ok: true, host })
    })

    test.each([
        ['an empty value', '  '],
        ['plain http to a remote host', 'http://posthog.example.com'],
        ['a non-web scheme', 'ftp://posthog.example.com'],
        ['a script URL', 'javascript:alert(1)'],
    ])('rejects %s', (_name, input) => {
        expect(validateHost(input)).toMatchObject({ ok: false })
    })

    test.each([
        ['http://localhost:8010', false],
        ['http://127.0.0.1:8000', false],
        ['https://localhost:8010', true],
    ])('a store build given %s accepts it: %s', (input, ok) => {
        expect(validateHost(input, false)).toMatchObject({ ok })
    })
})
