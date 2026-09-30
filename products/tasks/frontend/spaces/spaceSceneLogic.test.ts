import { expectLogic } from 'kea-test-utils'

import { todaySessionMenuLogic } from '~/layout/today/todaySessionMenuLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { spaceSceneLogic } from './spaceSceneLogic'

describe('spaceSceneLogic', () => {
    let sessionSpace = 'space-a'

    beforeEach(() => {
        sessionSpace = 'space-a'
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/task_channels/:id/': ({ params }) => [
                    200,
                    { id: params.id, name: String(params.id), system_role: null },
                ],
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const channel = new URL(request.url).searchParams.get('channel')
                    const results =
                        channel === sessionSpace
                            ? [{ id: 'task-1', title: 'Session', channel, archived: false, last_activity_at: null }]
                            : []
                    return [200, { results, count: results.length }]
                },
            },
            patch: {
                '/api/projects/:team_id/tasks/:id/': async ({ request }) => {
                    const body = (await request.json()) as { channel?: string }
                    sessionSpace = body.channel ?? sessionSpace
                    return [200, { id: 'task-1', channel: sessionSpace }]
                },
            },
        })
        initKeaTests()
    })

    it('drops a session from the feed when the row menu moves it to another space', async () => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.feedGroups.flatMap((group) => group.items.map((item) => item.id))).toEqual(['task-1'])

        todaySessionMenuLogic.actions.moveSession('task-1', 'space-b')
        await expectLogic(logic).toDispatchActions(['sessionUpdated', 'loadSessionsSuccess'])

        expect(logic.values.feedGroups).toEqual([])
    })
})
