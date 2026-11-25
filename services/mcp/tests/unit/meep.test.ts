import { describe, expect, it, vi } from 'vitest'

import { meepToolsToExclude } from '@/hono/request-state-resolver'
import { GENERATED_TOOLS } from '@/tools/generated/meep'
import type { Context } from '@/tools/types'

describe('Meep session tools', () => {
    const reads = ['meep:read', 'meep_scout:read']
    const writes = [...reads, 'meep_scout:write']
    it('limits discovery to the task that holds a server-issued Meep credential', () => {
        for (const excluded of [
            meepToolsToExclude(undefined, undefined, writes),
            meepToolsToExclude('other-task', 'task-1', writes),
            meepToolsToExclude('task-1', 'task-1', ['meep:read', 'meep:write']),
        ]) {
            expect(excluded).toEqual(
                expect.arrayContaining(['meep-topic-get', 'meep-scout-create', 'meep-scout-set-enabled'])
            )
        }
        expect(meepToolsToExclude('task-1', 'task-1', reads)).toEqual(
            expect.arrayContaining(['meep-scout-create', 'meep-scout-set-enabled'])
        )
        expect(meepToolsToExclude('task-1', 'task-1', writes)).toEqual([])
    })

    it('uses the authenticated project and routes both operations through the bound topic', async () => {
        const request = vi.fn().mockResolvedValue({})
        const context = { api: { request }, stateManager: { getProjectId: async () => '42' } } as unknown as Context
        const topic = 'ea8042a5-16cc-46e7-88a1-4ac678ac947c'
        const scout = '7fd113d5-aefe-4dbf-a4ae-505c1138a6b8'
        const body = { name: 'Activation', instructions: 'Report material changes to activation.' }
        const create = GENERATED_TOOLS['meep-scout-create']!()
        const toggle = GENERATED_TOOLS['meep-scout-set-enabled']!()
        await create.handler(context, create.schema.parse({ id: topic, ...body }))
        await toggle.handler(context, toggle.schema.parse({ id: topic, scout_id: scout, enabled: false }))
        expect(request.mock.calls).toEqual([
            [{ method: 'POST', path: `/api/projects/42/meep/topics/${topic}/scouts/`, body }],
            [
                {
                    method: 'POST',
                    path: `/api/projects/42/meep/topics/${topic}/scout-status/`,
                    body: { scout_id: scout, enabled: false },
                },
            ],
        ])
    })
})
