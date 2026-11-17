import { signInReturnFor, signInReturnHref, signInReturnParam } from './signInReturn'

describe('signInReturn', () => {
    test.each<[string, string[], Record<string, string | string[] | undefined>, string | null]>([
        [
            '/report/0192-abc',
            ['report', '[id]'],
            { id: '0192-abc', from: 'link', project: '7', host: 'eu.posthog.com' },
            '/report/0192-abc?from=link&project=7&host=eu.posthog.com',
        ],
        ['/', [], {}, null],
        ['/inbox', ['(tabs)', 'inbox'], {}, null],
        ['/sign-in', ['sign-in'], { next: '/report/x' }, null],
    ])('returns to %s', (pathname, segments, params, expected) => {
        expect(signInReturnHref(pathname, segments, params)).toBe(expected)
    })

    test.each<[string | undefined, string | null]>([
        ['/report/0192-abc?from=link', '/report/0192-abc?from=link'],
        [undefined, null],
        ['https://evil.example.com', null],
        ['//evil.example.com', null],
        ['/sign-in?next=/report/x', null],
    ])('accepts %s as next', (value, expected) => {
        expect(signInReturnParam(value)).toBe(expected)
    })

    test.each<[string, string | undefined, string | null]>([
        ['account-a', 'account-a', '/report/0192-abc'],
        ['account-b', 'account-b', null],
        ['a link that names no account', undefined, '/report/0192-abc'],
    ])('reopens next for a screen left by %s once account-a signs in', (_name, owner, expected) => {
        expect(signInReturnFor('/report/0192-abc', owner, 'account-a')).toBe(expected)
    })
})
