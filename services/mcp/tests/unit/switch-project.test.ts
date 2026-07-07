import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PostHogPermissionError } from '@/lib/errors'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import setActiveProjectTool from '@/tools/projects/setActive'
import type { Context, State } from '@/tools/types'

// Guards the regression where switch-project accepted an inaccessible project id,
// cached it, and returned success — leaving every later tool call 403ing with no
// recovery signal. The switch must be validated against the key before it commits.
describe('switch-project', () => {
    let cache: MemoryCache<State>

    const accessibleProject = { id: 42, name: 'Accessible', organization: 'org-1', uuid: 'uuid-42' }

    function createContext(overrides: {
        projectGet: ReturnType<typeof vi.fn>
        projectsList?: ReturnType<typeof vi.fn>
    }): Context {
        const projectsList =
            overrides.projectsList ??
            vi.fn().mockResolvedValue({
                success: true,
                data: [{ id: 42, name: 'Accessible' }],
            })
        return {
            api: {
                projects: () => ({ get: overrides.projectGet }),
                organizations: () => ({ projects: () => ({ list: projectsList }) }),
                publicBaseUrl: 'https://us.posthog.com',
            } as any,
            cache,
            stateManager: {
                getUser: vi.fn().mockResolvedValue({ organizations: [{ id: 'org-1', name: 'Org 1' }] }),
                getApiKey: vi.fn().mockResolvedValue({ scopes: [], scoped_teams: [], scoped_organizations: [] }),
            } as any,
            env: {} as any,
            sessionManager: {} as any,
            getDistinctId: async () => 'distinct-1',
            trackEvent: async () => {},
        }
    }

    beforeEach(async () => {
        cache = new MemoryCache('switch-project-test')
        await cache.clear()
        await cache.set('projectId', '7')
    })

    it('commits the switch when the key can access the target project', async () => {
        const projectGet = vi.fn().mockResolvedValue({ success: true, data: accessibleProject })
        const result = await setActiveProjectTool().handler(createContext({ projectGet }), { projectId: 42 })

        expect(result.content[0]!.text).toContain('Switched to project 42')
        expect(await cache.get('projectId')).toBe('42')
    })

    it('rejects the switch and leaves the active project unchanged when access is denied', async () => {
        const projectGet = vi.fn().mockResolvedValue({
            success: false,
            error: new PostHogPermissionError({ detail: 'permission denied', url: 'x', method: 'GET' }),
        })

        await expect(
            setActiveProjectTool().handler(createContext({ projectGet }), { projectId: 128076 })
        ).rejects.toThrow(/Cannot switch to project 128076/)

        // The pre-existing active project must survive a failed switch.
        expect(await cache.get('projectId')).toBe('7')
    })

    it('lists accessible projects in the error so the agent can self-correct', async () => {
        const projectGet = vi.fn().mockResolvedValue({
            success: false,
            error: new Error('403'),
        })

        await expect(
            setActiveProjectTool().handler(createContext({ projectGet }), { projectId: 128076 })
        ).rejects.toThrow(/42 \(Accessible/)
    })
})
