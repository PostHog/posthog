import { manifest } from '../manifest'

describe('stamphog redirects', () => {
    test.each<[string, Record<string, any>, string]>([
        ['/stamphog', { repo: 'web' }, '/code-review?repo=web&tab=approval_settings'],
        ['/stamphog/runs', { page: '2' }, '/code-review?page=2&tab=approval_history'],
        ['/stamphog/area', { team: 'team-web' }, '/code-review?team=team-web&tab=code_you_own'],
        ['/stamphog/digests', { page: '3' }, '/code-review?tab=approval_settings&digests=1&digests_page=3'],
    ])('forwards %s to its Code review tab', (path, searchParams, expected) => {
        const redirect = manifest.redirects?.[path]
        expect(typeof redirect).toBe('function')
        expect((redirect as (...args: any[]) => string)({}, searchParams, {})).toEqual(expected)
    })
})
