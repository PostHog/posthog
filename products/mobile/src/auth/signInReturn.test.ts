import { signInReturnHref, signInReturnParam } from './signInReturn'

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
})
