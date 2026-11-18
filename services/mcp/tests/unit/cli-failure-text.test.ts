import { describe, expect, it } from 'vitest'

import { failureText, isRunningInCI } from '@/cli/utils'
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
        ['Cloudflare Workers', { WORKERS_CI: '1' }, true],
        ['Cloudflare Workers with CI=false', { CI: 'false', WORKERS_CI: '1' }, true],
        ['Render', { RENDER: 'true' }, true],
        ['Railway', { RAILWAY_SERVICE_ID: 'synthetic-service' }, true],
        ['Heroku CI', { HEROKU_TEST_RUN_ID: 'synthetic-run' }, true],
        ['Xcode Cloud', { CI_XCODE_CLOUD: 'TRUE' }, true],
        ['a terminal', {}, false],
    ])('detects CI from %s', (_name, env, expected) => {
        expect(isRunningInCI(env)).toBe(expected)
    })

    it.each([
        ['outside CI shows', false, true],
        ['in CI hides', true, false],
    ])("%s PostHog's reason", (_name, isCI, shown) => {
        const text = failureText(refused, isCI)

        expect(text.startsWith(refused.message)).toBe(true)
        expect(text.includes('Enter a number. (field: limit)')).toBe(shown)
        expect(text.includes('hidden in CI')).toBe(!shown)
    })

    it.each([
        ['C0', 'before\u001bafter\u0007', 'before\\u001bafter\\u0007'],
        ['C1', 'before\u009dafter\u009c', 'before\\u009dafter\\u009c'],
    ])('escapes %s controls without changing the reference data', (_name, detail, escaped) => {
        const error = new PostHogValidationError({ ...refused, detail })
        const text = failureText(error, false)
        const reference = text.match(/<posthog-error-detail[^>]*>\n([\s\S]*?)\n<\/posthog-error-detail>/)

        expect(JSON.parse(reference?.[1] ?? '')).toEqual({ detail: `${detail} (field: limit)` })
        for (const control of ['\u001b', '\u0007', '\u009d', '\u009c']) {
            expect(text).not.toContain(control)
        }
        for (const isCI of [false, true]) {
            expect(failureText(new Error(`First line\n\t${detail}`), isCI)).toBe(`First line\n\t${escaped}`)
        }
    })

    it('keeps an error without a PostHog reason as it is', () => {
        expect(failureText(new Error('Unknown tool: "nope".'), true)).toBe('Unknown tool: "nope".')
    })
})
