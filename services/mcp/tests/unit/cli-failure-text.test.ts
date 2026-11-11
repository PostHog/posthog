import { describe, expect, it } from 'vitest'

import { failureText, isCi } from '@/cli/utils'
import { PostHogValidationError } from '@/lib/errors'

const refused = new PostHogValidationError({
    detail: 'Enter a number.',
    attr: 'limit',
    code: 'invalid',
    extra: undefined,
    url: 'https://us.posthog.com/api/projects/1/insights/',
    method: 'GET',
})

describe('CLI failure text', () => {
    it.each([
        ['CI=true', { CI: 'true' }, true],
        ['CI=false', { CI: 'false' }, false],
        ['Jenkins, which does not set CI', { JENKINS_URL: 'https://jenkins.example.com/' }, true],
        ['a terminal', {}, false],
    ])('detects CI from %s', (_name, env, expected) => {
        expect(isCi(env)).toBe(expected)
    })

    it.each([
        ['outside CI shows', false, true],
        ['in CI hides', true, false],
    ])("%s PostHog's reason", (_name, ci, shown) => {
        const text = failureText(refused, ci)

        expect(text.startsWith(refused.message)).toBe(true)
        expect(text.includes('Enter a number. (field: limit)')).toBe(shown)
        expect(text.includes('hidden in CI')).toBe(!shown)
    })

    it('keeps an error without a PostHog reason as it is', () => {
        expect(failureText(new Error('Unknown tool: "nope".'), true)).toBe('Unknown tool: "nope".')
    })
})
