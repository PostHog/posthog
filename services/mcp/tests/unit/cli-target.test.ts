import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildCliContext } from '@/cli/context'
import { MissingProjectContextError } from '@/lib/errors'

vi.mock('@/lib/posthog', () => ({ getPostHogClient: () => ({ capture: vi.fn(), captureException: vi.fn() }) }))

describe('CLI invocation targets', () => {
    afterEach(() => vi.unstubAllGlobals())

    it('keeps overlapping invocations on their own project and organization with the same credential', async () => {
        const [first, second] = await Promise.all([
            buildCliContext({
                apiKey: 'phx_example',
                host: 'https://example.com',
                version: 2,
                projectId: '11',
                organizationId: 'org-a',
            }),
            buildCliContext({
                apiKey: 'phx_example',
                host: 'https://example.com',
                version: 2,
                projectId: '22',
                organizationId: 'org-b',
            }),
        ])

        expect(
            await Promise.all([
                first.stateManager.getProjectId(),
                first.stateManager.getOrgID(),
                second.stateManager.getProjectId(),
                second.stateManager.getOrgID(),
            ])
        ).toEqual(['11', 'org-a', '22', 'org-b'])
    })

    it('derives a project-only target organization from the project rather than the website default', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => Response.json({ id: 22, organization: 'org-b' }))
        )
        const context = await buildCliContext({
            apiKey: 'phx_project',
            host: 'https://example.com',
            version: 2,
            projectId: '22',
        })
        await context.cache.set('orgId', 'org-a')

        expect(await context.stateManager.getOrgID()).toBe('org-b')
    })

    it('refuses to fall back to another organization when an org-only target needs a project', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async (url: string) =>
                Response.json(
                    url.includes('/projects/')
                        ? { id: 11, organization: 'org-a' }
                        : { organization: { id: 'org-a' }, team: { id: 11 } }
                )
            )
        )
        const context = await buildCliContext({
            apiKey: 'phx_org',
            host: 'https://example.com',
            version: 2,
            organizationId: 'org-b',
        })
        await context.cache.setMany({
            projectId: '11',
            apiKey: { scopes: [], scoped_teams: [], scoped_organizations: [] },
            apiKeyFetchedAt: Date.now(),
        })

        await expect(context.stateManager.getProjectId()).rejects.toBeInstanceOf(MissingProjectContextError)
    })
})
