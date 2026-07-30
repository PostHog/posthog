import { afterEach, describe, expect, it } from 'vitest'

import { resolveCliConfig } from '@/cli/config'

const ENV_VARS = [
    'POSTHOG_PROJECT_ID',
    'POSTHOG_CLI_PROJECT_ID',
    'POSTHOG_CLI_ENV_ID',
    'POSTHOG_ORGANIZATION_ID',
    'POSTHOG_CLI_ORGANIZATION_ID',
]

describe('resolveCliConfig', () => {
    afterEach(() => {
        for (const name of ENV_VARS) {
            delete process.env[name]
        }
    })

    it.each([
        ['unsubstituted placeholder', '${POSTHOG_PROJECT_ID}', 'the variable was never substituted'],
        ['bare shell placeholder', '$POSTHOG_PROJECT_ID', 'the variable was never substituted'],
        ['doc placeholder', 'YOUR_POSTHOG_PROJECT_ID', 'that is a documentation placeholder'],
        ['project API key', 'phc_abc123secret', 'that is a project API key, not a project id'],
        ['environment slug', 'moxsea-production', 'project ids are numeric'],
    ])('rejects a %s with an actionable message', (_name, value, reason) => {
        process.env.POSTHOG_PROJECT_ID = value
        expect(() => resolveCliConfig()).toThrow(new RegExp(`POSTHOG_PROJECT_ID is set to .*${reason}`))
        expect(() => resolveCliConfig()).toThrow(/us\.posthog\.com\/project/)
    })

    it('never echoes a pasted project API key back into the error message', () => {
        process.env.POSTHOG_CLI_PROJECT_ID = 'phc_abc123secret'
        expect(() => resolveCliConfig()).toThrow(/POSTHOG_CLI_PROJECT_ID is set to phc_…/)
        expect(() => resolveCliConfig()).not.toThrow(/abc123secret/)
    })

    it.each([
        ['surrounding double quotes', '"12345"'],
        ['surrounding single quotes', "'12345'"],
        ['whitespace', '  12345\n'],
    ])('normalizes a project id with %s', (_name, value) => {
        process.env.POSTHOG_PROJECT_ID = value
        expect(resolveCliConfig().projectId).toBe('12345')
    })

    it('rejects an organization id placeholder but accepts a UUID', () => {
        process.env.POSTHOG_ORGANIZATION_ID = '${POSTHOG_ORGANIZATION_ID}'
        expect(() => resolveCliConfig()).toThrow(/POSTHOG_ORGANIZATION_ID is set to/)

        process.env.POSTHOG_ORGANIZATION_ID = '"018e0000-0000-0000-0000-000000000000"'
        expect(resolveCliConfig().organizationId).toBe('018e0000-0000-0000-0000-000000000000')
    })
})
