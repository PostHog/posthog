import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
import getProjectTool from '@/tools/projects/getProject'
import getProjectsTool from '@/tools/projects/getProjects'
import type { Context } from '@/tools/types'

const PROJECTS = [
    { id: 1, name: 'Production' },
    { id: 2, name: 'Staging' },
    { id: 3, name: 'Marketing site' },
]

function makeContext(opts: {
    request?: ReturnType<typeof vi.fn>
    projects?: unknown[]
    listSuccess?: boolean
    orgId?: string
    activeProjectId?: number
}): Context {
    const list = vi
        .fn()
        .mockResolvedValue(
            opts.listSuccess === false
                ? { success: false, error: new Error('nope') }
                : { success: true, data: opts.projects ?? PROJECTS }
        )
    return {
        api: {
            request: opts.request ?? vi.fn(),
            organizations: () => ({ projects: () => ({ list }) }),
        } as any,
        stateManager: {
            getOrgID: vi.fn().mockResolvedValue(opts.orgId ?? 'org-1'),
            getProjectId: vi.fn().mockResolvedValue(opts.activeProjectId),
        } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

function apiError(status: number): PostHogApiError {
    return new PostHogApiError({
        status,
        statusText: 'error',
        body: '{}',
        url: 'https://us.posthog.com/api/organizations/org-1/projects/999/',
        method: 'GET',
    })
}

describe('project-get handler', () => {
    it('returns the project on success, stripping secret fields', async () => {
        const request = vi.fn().mockResolvedValue({ id: 1, name: 'Production', secret_api_token: 'phs_secret' })
        const result = (await getProjectTool().handler(makeContext({ request }), { id: 1 })) as unknown as Record<
            string,
            unknown
        >

        expect(result.name).toBe('Production')
        expect(result).not.toHaveProperty('secret_api_token')
    })

    it.each([[403], [404]])(
        'degrades to accessible projects + guidance on a %i instead of throwing',
        async (status) => {
            const request = vi.fn().mockRejectedValue(apiError(status))
            const result = (await getProjectTool().handler(makeContext({ request }), {
                id: 999,
            })) as unknown as Record<string, unknown>

            expect(result.requested_project_id).toBe(999)
            expect(result.accessible_projects).toEqual([
                { id: 1, name: 'Production' },
                { id: 2, name: 'Staging' },
                { id: 3, name: 'Marketing site' },
            ])
            expect(result.guidance).toContain('projects-get')
            expect(result).not.toHaveProperty('isError')
        }
    )

    it('still degrades gracefully when listing accessible projects also fails', async () => {
        const request = vi.fn().mockRejectedValue(apiError(404))
        const result = (await getProjectTool().handler(makeContext({ request, listSuccess: false }), {
            id: 999,
        })) as unknown as Record<string, unknown>

        expect(result.accessible_projects).toEqual([])
        expect(result.guidance).toContain('projects-get')
    })

    it('propagates non-recoverable failures (5xx) rather than masking them', async () => {
        const request = vi.fn().mockRejectedValue(apiError(500))
        await expect(getProjectTool().handler(makeContext({ request }), { id: 1 })).rejects.toThrow(/500/)
    })
})

describe('projects-get handler', () => {
    it.each([
        ['prod', [{ id: 1, name: 'Production' }]],
        ['SITE', [{ id: 3, name: 'Marketing site' }]],
        ['nonexistent', []],
    ])('filters by case-insensitive substring %s', async (name, expected) => {
        const result = await getProjectsTool().handler(makeContext({}), { name })
        expect(result).toEqual(expected)
    })

    it('returns all projects when no name filter is given', async () => {
        const result = await getProjectsTool().handler(makeContext({}), {})
        expect(result).toEqual(PROJECTS)
    })
})
