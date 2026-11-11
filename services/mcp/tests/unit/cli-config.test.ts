import { afterEach, describe, expect, it, vi } from 'vitest'

import { resolveCliConfig } from '@/cli/config'

describe('CLI target configuration', () => {
    afterEach(() => vi.unstubAllEnvs())

    it.each([
        { flags: ['--project-id', '22'], expected: { projectId: '22' } },
        { flags: ['--organization-id', 'org-b'], expected: { organizationId: 'org-b' } },
        {
            flags: ['--organization-id', 'org-b', '--project-id', '22'],
            expected: { organizationId: 'org-b', projectId: '22' },
        },
        { flags: [], expected: { organizationId: 'org-a', projectId: '11' } },
    ])('resolves $flags without mixing explicit and inherited targets', ({ flags, expected }) => {
        vi.stubEnv('POSTHOG_API_KEY', 'phx_example')
        vi.stubEnv('POSTHOG_ORGANIZATION_ID', 'org-a')
        vi.stubEnv('POSTHOG_PROJECT_ID', '11')
        const args = [...flags, 'feature-flag-get-all', '{}']

        expect(resolveCliConfig(args)).toEqual({
            apiKey: 'phx_example',
            host: 'https://us.posthog.com',
            version: 2,
            ...expected,
        })
        expect(args).toEqual(['feature-flag-get-all', '{}'])
    })

    it.each(['--project-id', '--organization-id'])('rejects a missing value for %s', (flag) => {
        expect(() => resolveCliConfig([flag])).toThrow(`Missing value for ${flag}`)
    })
})
