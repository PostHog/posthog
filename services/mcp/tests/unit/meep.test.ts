import { describe, expect, it, vi } from 'vitest'

import { meepToolsToExclude } from '@/hono/request-state-resolver'
import { GENERATED_TOOLS } from '@/tools/generated/meep'
import type { Context } from '@/tools/types'

describe('Meep session tools', () => {
    const reads = ['meep:read', 'meep_scout:read']
    const writes = [...reads, 'meep_scout:write', 'meep_task:write']
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
            expect.arrayContaining([
                'meep-scout-create',
                'meep-scout-set-enabled',
                'meep-task-start',
                'meep-task-wait',
                'meep-task-answer',
            ])
        )
        expect(meepToolsToExclude('task-1', 'task-1', [...reads, 'meep_scout:write'])).toEqual(
            expect.arrayContaining(['meep-task-start', 'meep-task-wait', 'meep-task-answer'])
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

    it('routes task operations through the bound topic', async () => {
        const request = vi.fn().mockResolvedValue({})
        const context = { api: { request }, stateManager: { getProjectId: async () => '42' } } as unknown as Context
        const id = 'ea8042a5-16cc-46e7-88a1-4ac678ac947c'
        const request_id = '7fd113d5-aefe-4dbf-a4ae-505c1138a6b8'
        const item_id = 'a47f3d2b-5c29-45b7-b2cf-1c371037a1db'
        const question_run_id = '114da288-65bd-47bd-9e96-1f12465473e6'
        const start = GENERATED_TOOLS['meep-task-start']!()
        const wait = GENERATED_TOOLS['meep-task-wait']!()
        const answer = GENERATED_TOOLS['meep-task-answer']!()
        await start.handler(
            context,
            start.schema.parse({ id, request_id, title: 'Investigate', brief: 'Find the cause.' })
        )
        await wait.handler(context, wait.schema.parse({ id, request_id, item_ids: [item_id] }))
        await answer.handler(context, answer.schema.parse({ id, request_id, item_id, question_run_id, answer: 'Yes.' }))
        expect(request.mock.calls).toEqual([
            [
                {
                    method: 'POST',
                    path: `/api/projects/42/meep/topics/${id}/tasks/start/`,
                    body: { request_id, title: 'Investigate', brief: 'Find the cause.' },
                },
            ],
            [
                {
                    method: 'POST',
                    path: `/api/projects/42/meep/topics/${id}/tasks/wait/`,
                    body: { request_id, item_ids: [item_id] },
                },
            ],
            [
                {
                    method: 'POST',
                    path: `/api/projects/42/meep/topics/${id}/tasks/answer/`,
                    body: { request_id, item_id, question_run_id, answer: 'Yes.' },
                },
            ],
        ])
    })
})
