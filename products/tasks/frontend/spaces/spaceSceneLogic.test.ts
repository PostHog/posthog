import { expectLogic } from 'kea-test-utils'

import { todaySessionMenuLogic } from '~/layout/today/todaySessionMenuLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { spaceSceneLogic } from './spaceSceneLogic'

describe('spaceSceneLogic', () => {
    let sessionSpace = 'space-a'
    let createdTaskBody: Record<string, unknown> | null = null
    let runBody: Record<string, unknown> | null = null
    let deletedTaskId: string | null = null

    beforeEach(() => {
        sessionSpace = 'space-a'
        createdTaskBody = null
        runBody = null
        deletedTaskId = null
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/task_channels/:id/': ({ params }) => [
                    200,
                    { id: params.id, name: String(params.id), system_role: null },
                ],
                '/api/projects/:team_id/task_channels/:id/members/': [
                    { id: 7, uuid: 'user-7', first_name: 'Ada', email: 'ada@example.com' },
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
            post: {
                '/api/projects/:team_id/tasks/': async ({ request }) => {
                    createdTaskBody = (await request.json()) as Record<string, unknown>
                    return [201, { id: 'task-new', channel: createdTaskBody.channel }]
                },
                '/api/projects/:team_id/tasks/:id/run/': async ({ request }) => {
                    runBody = (await request.json()) as Record<string, unknown>
                    return [200, { id: 'task-new', run: { id: 'run-1' } }]
                },
            },
            delete: {
                '/api/projects/:team_id/tasks/:id/': ({ params }) => {
                    deletedTaskId = String(params.id)
                    return [204]
                },
            },
            patch: {
                '/api/projects/:team_id/task_channels/:id/': async ({ params, request }) => [
                    200,
                    { id: params.id, system_role: null, ...((await request.json()) as Record<string, unknown>) },
                ],
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

    it('shows the new name after a rename and reloads the sidebar spaces', async () => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.updateSpace({ name: 'checkout' })
        await expectLogic(logic).toDispatchActions(['updateSpace', 'spaceSaved', 'loadSpaces'])

        expect(logic.values.space?.name).toBe('checkout')
        expect(logic.values.savingSpace).toBe(false)
    })

    it.each([
        [404, true],
        [500, false],
    ])('treats a %s space load as missing: %s', async (status, missing) => {
        useMocks({
            get: { '/api/projects/:team_id/task_channels/:id/': () => [status, { detail: 'Error' }] },
        })
        const logic = spaceSceneLogic({ id: 'space-gone' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSpaceFailure'])

        expect(logic.values.spaceMissing).toBe(missing)
        expect(logic.values.spaceUnavailable).toBe(true)
    })

    it('loads the members once the space turns private', async () => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.members).toEqual([])

        logic.actions.updateSpace({ channel_type: 'private' })
        await expectLogic(logic).toDispatchActions(['spaceSaved', 'loadMembersSuccess'])

        expect(logic.values.members.map((member) => member.id)).toEqual([7])
    })

    it('starts the session in this space and clears the field', async () => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setTaskDraft('  Fix the checkout bug  ')
        logic.actions.createTask()
        await expectLogic(logic).toDispatchActions(['createTaskSuccess', 'loadSessionsSuccess'])

        expect(createdTaskBody).toMatchObject({ description: 'Fix the checkout bug', channel: 'space-a' })
        expect(runBody).toMatchObject({ mode: 'interactive', pending_user_message: 'Fix the checkout bug' })
        expect(logic.values).toMatchObject({ creatingTask: false, taskDraft: '' })
    })

    it.each([
        ['the task create', '/api/projects/:team_id/tasks/', null],
        ['the run start', '/api/projects/:team_id/tasks/:id/run/', 'task-new'],
    ])('keeps the prompt and unlocks the field when %s fails', async (_, failingUrl, expectedDeletedTaskId) => {
        useMocks({ post: { [failingUrl]: () => [500, { detail: 'Error' }] } })
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setTaskDraft('Fix the checkout bug')
        logic.actions.createTask()
        await expectLogic(logic).toDispatchActions(['createTaskFailure'])

        expect(logic.values).toMatchObject({ creatingTask: false, taskDraft: 'Fix the checkout bug' })
        expect(deletedTaskId).toBe(expectedDeletedTaskId)
    })
})
