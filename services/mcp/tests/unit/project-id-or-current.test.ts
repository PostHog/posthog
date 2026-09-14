import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/core'
import type { Context } from '@/tools/types'

/**
 * The project tools advertise `@current` while the path param stays an integer,
 * so the two spellings agents actually send — `@current` and no `id` at all —
 * both died at the boundary instead of reaching the active project.
 */
describe('project id or @current', () => {
    function mockContext(request: ReturnType<typeof vi.fn>): Context {
        return {
            api: { request },
            stateManager: { getOrgID: async () => 'org-1', getProjectId: async () => '42' },
        } as unknown as Context
    }

    it.each([
        { name: 'omitted', input: {} },
        { name: '@current', input: { id: '@current' } },
    ])('project-settings-update targets the active project when id is $name', async ({ input }) => {
        const request = vi.fn().mockResolvedValue({ id: 42 })
        const tool = GENERATED_TOOLS['project-settings-update']!()

        await tool.handler(mockContext(request), tool.schema.parse({ ...input, session_recording_opt_in: true }))

        expect(request).toHaveBeenCalledWith({
            method: 'PATCH',
            path: '/api/organizations/org-1/projects/42/',
            body: { session_recording_opt_in: true },
        })
    })

    it.each([
        { name: 'a number', id: 7 },
        { name: 'a stringified number', id: '7' },
    ])('project-settings-update targets the named project when id is $name', async ({ id }) => {
        const request = vi.fn().mockResolvedValue({ id: 7 })
        const tool = GENERATED_TOOLS['project-settings-update']!()

        await tool.handler(mockContext(request), tool.schema.parse({ id, name: 'Storefront' }))

        expect(request).toHaveBeenCalledWith({
            method: 'PATCH',
            path: '/api/organizations/org-1/projects/7/',
            body: { name: 'Storefront' },
        })
    })

    it('project-get reads the active project when id is @current', async () => {
        const request = vi.fn().mockResolvedValue({ id: 42 })
        const tool = GENERATED_TOOLS['project-get']!()

        await tool.handler(mockContext(request), tool.schema.parse({ id: '@current' }))

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/organizations/org-1/projects/42/',
        })
    })
})
