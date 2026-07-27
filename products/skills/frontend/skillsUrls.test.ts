import { urls } from 'scenes/urls'

import { productRedirects } from '~/products'

type RedirectParams = Record<string, string>

const redirectUrl = (
    path: string,
    params: RedirectParams = {},
    searchParams: RedirectParams = {},
    hashParams: RedirectParams = {}
): string => {
    const redirect = productRedirects[path]
    return typeof redirect === 'function' ? redirect(params, searchParams, hashParams) : redirect
}

describe('Skills product URLs', () => {
    it('serves skills at the top-level /skills route', () => {
        expect(urls.skills()).toBe('/skills')
        expect(urls.skill('signals-dwh')).toBe('/skills/signals-dwh')
        expect(urls.skill('signals-dwh', { file: 'SKILL.md', version: 2 })).toBe(
            '/skills/signals-dwh?file=SKILL.md&version=2'
        )
    })

    it.each([
        ['/prompt-management/skills', {}, '/skills'],
        ['/prompt-management/skills/:name', { name: 'skill-1' }, '/skills/skill-1'],
        ['/llm-analytics/skills', {}, '/skills'],
        ['/llm-analytics/skills/:name', { name: 'skill-1' }, '/skills/skill-1'],
    ] as [string, RedirectParams, string][])('redirects legacy URL %s to %s', (path, params, expected) => {
        expect(redirectUrl(path, params)).toBe(expected)
    })
})
