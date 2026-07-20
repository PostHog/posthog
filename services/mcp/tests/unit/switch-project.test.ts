import { describe, expect, it, vi } from 'vitest'

import setActiveProjectTool from '@/tools/projects/setActive'
import type { Context } from '@/tools/types'

const ACTIVE_ORG = 'org-active'
const OTHER_ORG = 'org-other'

function createMockContext(overrides: {
    projectGet: ReturnType<typeof vi.fn>
    organizationGet?: ReturnType<typeof vi.fn>
    initialOrgId?: string
}): { context: Context; cache: Map<string, unknown> } {
    const cache = new Map<string, unknown>()
    if (overrides.initialOrgId) {
        cache.set('orgId', overrides.initialOrgId)
    }
    const context = {
        api: {
            publicBaseUrl: 'https://us.posthog.com',
            projects: () => ({ get: overrides.projectGet }),
            organizations: () => ({ get: overrides.organizationGet ?? vi.fn() }),
        },
        cache: {
            get: async (key: string) => cache.get(key),
            set: async (key: string, value: unknown) => {
                cache.set(key, value)
            },
        },
        stateManager: {},
        env: {},
        sessionManager: {},
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
    return { context, cache }
}

describe('switch-project', () => {
    const tool = setActiveProjectTool()

    it('does not commit the session and returns actionable guidance when the project is unreachable', async () => {
        const projectGet = vi.fn().mockResolvedValue({ success: false, error: new Error('404') })
        const { context, cache } = createMockContext({ projectGet, initialOrgId: ACTIVE_ORG })

        await expect(tool.handler(context, { projectId: 999 })).rejects.toThrow(
            /Could not switch to project 999.*active organization \(org-active\).*organizations-get.*switch-organization/s
        )
        // A failed switch must not strand the session on an unreachable project.
        expect(cache.get('projectId')).toBeUndefined()
    })

    it('switches to a project in the active organization without touching the active org', async () => {
        const projectGet = vi.fn().mockResolvedValue({
            success: true,
            data: { id: 42, name: 'My project', organization: ACTIVE_ORG },
        })
        const organizationGet = vi.fn()
        const { context, cache } = createMockContext({ projectGet, organizationGet, initialOrgId: ACTIVE_ORG })

        const result = await tool.handler(context, { projectId: 42 })

        expect(result.content[0]!.text).toContain('Switched to project 42')
        expect(result.content[0]!.text).not.toContain('also switched the active organization')
        expect(cache.get('projectId')).toBe('42')
        expect(cache.get('orgId')).toBe(ACTIVE_ORG)
        expect(organizationGet).not.toHaveBeenCalled()
    })

    it('syncs the active organization when the project belongs to a different org', async () => {
        const projectGet = vi.fn().mockResolvedValue({
            success: true,
            data: { id: 77, name: 'Cross-org project', organization: OTHER_ORG },
        })
        const organizationGet = vi.fn().mockResolvedValue({
            success: true,
            data: { id: OTHER_ORG, name: 'Other org' },
        })
        const { context, cache } = createMockContext({ projectGet, organizationGet, initialOrgId: ACTIVE_ORG })

        const result = await tool.handler(context, { projectId: 77 })

        expect(result.content[0]!.text).toContain('also switched the active organization to org-other')
        expect(cache.get('projectId')).toBe('77')
        expect(cache.get('orgId')).toBe(OTHER_ORG)
        expect(organizationGet).toHaveBeenCalledWith({ orgId: OTHER_ORG })
    })
})
