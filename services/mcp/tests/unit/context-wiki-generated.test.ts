import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { GENERATED_TOOLS as CANVAS_TOOLS } from '@/tools/generated/canvas'
import { GENERATED_TOOLS } from '@/tools/generated/context_layer'
import type { Context, State } from '@/tools/types'

function createMockContext(): Context {
    const api = new ApiClient({ apiToken: 'test-token', baseUrl: 'https://us.posthog.test' })
    const cache = new MemoryCache<State>('context-wiki-generated-test')
    const stateManager = new StateManager(cache, api)
    vi.spyOn(stateManager, 'getProjectId').mockResolvedValue('42')
    vi.spyOn(stateManager, 'getOrgID').mockRejectedValue(new Error('organization route must not be used'))

    return {
        api,
        stateManager,
        env: {
            MCP_APPS_BASE_URL: undefined,
            POSTHOG_ANALYTICS_API_KEY: undefined,
            POSTHOG_ANALYTICS_HOST: undefined,
            POSTHOG_API_BASE_URL: undefined,
            POSTHOG_PUBLIC_URL: undefined,
            POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
            POSTHOG_UI_APPS_TOKEN: undefined,
        },
        sessionManager: new SessionManager(cache),
        cache,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('generated context read tools', () => {
    it.each(['context-wiki-page-retrieve', 'loop-context-wiki-page-retrieve', 'task-context-wiki-page-retrieve'])(
        '%s forwards bounded reads and the revision',
        async (name) => {
            const context = createMockContext()
            const request = vi.spyOn(context.api, 'request').mockResolvedValue({})
            const tool = GENERATED_TOOLS[name]!()
            const params = tool.schema.parse({ path: 'areas/analytics.md', offset: 12, head_sha: 'a'.repeat(40) })

            await tool.handler(context, params)

            expect(request).toHaveBeenCalledWith({
                method: 'GET',
                path: '/api/projects/42/context_layer/agent/pages/',
                query: { path: 'areas/analytics.md', offset: 12, head_sha: 'a'.repeat(40), limit: 12000 },
            })
        }
    )

    it('defaults canvas reads to a bounded key inventory', async () => {
        const context = createMockContext()
        const request = vi
            .spyOn(context.api, 'request')
            .mockResolvedValue({ entries: [], complete: true, next_offset: null })
        const tool = CANVAS_TOOLS['canvas-state-retrieve']!()
        const params = tool.schema.parse({ id: '00000000-0000-4000-8000-000000000001' })

        await tool.handler(context, params)

        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({
                method: 'GET',
                query: expect.objectContaining({ keys_only: true, limit: 20 }),
            })
        )
        expect(tool.schema.parse({ ...params, key: 'policy', keys_only: false })).toMatchObject({
            key: 'policy',
            keys_only: false,
        })
    })

    it('uses the project-nested route for ordinary task tokens', async () => {
        const context = createMockContext()
        const request = vi.spyOn(context.api, 'request').mockResolvedValue({
            path: 'projects/42/spaces/activation-research.md',
            exists: false,
        })

        await GENERATED_TOOLS['context-wiki-channel-resolve']!().handler(context, {
            channel_id: 'channel-id',
        })

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/context_layer/agent/channel-pages/channel-id/',
        })
    })
})
