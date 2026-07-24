import { describe, expect, it, vi } from 'vitest'

import setActiveProjectTool from '@/tools/projects/setActive'
import type { Context } from '@/tools/types'

const ACTIVE_ORG = 'org-active'
const OTHER_ORG = 'org-other'

function createMockContext(overrides: {
    projectGet: ReturnType<typeof vi.fn>
    getOrgID?: ReturnType<typeof vi.fn>
    getCachedOrFetchOrg?: ReturnType<typeof vi.fn>
}): { context: Context; cache: Map<string, unknown>; getCachedOrFetchOrg: ReturnType<typeof vi.fn> } {
    const cache = new Map<string, unknown>()
    const getCachedOrFetchOrg = overrides.getCachedOrFetchOrg ?? vi.fn().mockResolvedValue(undefined)
    const context = {
        api: {
            publicBaseUrl: 'https://us.posthog.com',
            projects: () => ({ get: overrides.projectGet }),
        },
        cache: {
            get: async (key: string) => cache.get(key),
            set: async (key: string, value: unknown) => {
                cache.set(key, value)
            },
        },
        stateManager: {
            getOrgID: overrides.getOrgID ?? vi.fn().mockResolvedValue(ACTIVE_ORG),
            getCachedOrFetchOrg,
        },
        env: {},
        sessionManager: {},
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
    return { context, cache, getCachedOrFetchOrg }
}

describe('switch-project', () => {
    const tool = setActiveProjectTool()

    it('does not commit the session, preserves the error cause, and guides the agent when the project is unreachable', async () => {
        const apiError = new Error('404')
        const projectGet = vi.fn().mockResolvedValue({ success: false, error: apiError })
        const { context, cache } = createMockContext({ projectGet })

        let caught: (Error & { cause?: unknown }) | undefined
        try {
            await tool.handler(context, { projectId: 999 })
        } catch (e) {
            caught = e as Error & { cause?: unknown }
        }

        expect(caught?.message).toMatch(
            /Could not switch to project 999.*active organization \(org-active\).*organizations-get.*switch-organization/s
        )
        // Keeping the typed error as cause keeps recoverable not-found/no-access
        // failures out of exception tracking.
        expect(caught?.cause).toBe(apiError)
        // A failed switch must not strand the session on an unreachable project.
        expect(cache.get('projectId')).toBeUndefined()
    })

    it('switches within the active organization without touching org state', async () => {
        const projectGet = vi.fn().mockResolvedValue({
            success: true,
            data: { id: 42, name: 'My project', organization: ACTIVE_ORG },
        })
        const { context, cache, getCachedOrFetchOrg } = createMockContext({ projectGet })

        const result = await tool.handler(context, { projectId: 42 })

        expect(result.content[0]!.text).toContain('Switched to project 42')
        expect(result.content[0]!.text).not.toContain('also switched the active organization')
        expect(cache.get('projectId')).toBe('42')
        expect(getCachedOrFetchOrg).not.toHaveBeenCalled()
    })

    it('syncs the active organization via the shared resolver when the project is in another org', async () => {
        const projectGet = vi.fn().mockResolvedValue({
            success: true,
            data: { id: 77, name: 'Cross-org project', organization: OTHER_ORG },
        })
        const getCachedOrFetchOrg = vi.fn().mockResolvedValue({ id: OTHER_ORG, name: 'Other org' })
        const { context, cache } = createMockContext({ projectGet, getCachedOrFetchOrg })

        const result = await tool.handler(context, { projectId: 77 })

        expect(result.content[0]!.text).toContain('also switched the active organization to org-other')
        expect(cache.get('projectId')).toBe('77')
        expect(cache.get('orgId')).toBe(OTHER_ORG)
        // Reuses the resolver (with its scoped-token guard) instead of calling the
        // org endpoint directly, which the backend rejects for project-scoped keys.
        expect(getCachedOrFetchOrg).toHaveBeenCalledTimes(1)
    })

    it('establishes org context without claiming a switch when no active org was resolved', async () => {
        const projectGet = vi.fn().mockResolvedValue({
            success: true,
            data: { id: 55, name: 'Scoped project', organization: OTHER_ORG },
        })
        // Team-scoped keys resolve no org on the first call, and getCachedOrFetchOrg
        // returns undefined for them (the org endpoint is rejected for such tokens).
        const getOrgID = vi.fn().mockRejectedValue(new Error('no org'))
        const { context, cache } = createMockContext({ projectGet, getOrgID })

        const result = await tool.handler(context, { projectId: 55 })

        expect(result.content[0]!.text).toContain('Switched to project 55')
        expect(result.content[0]!.text).not.toContain('also switched the active organization')
        expect(cache.get('orgId')).toBe(OTHER_ORG)
    })
})
