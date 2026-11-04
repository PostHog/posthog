import { expectLogic } from 'kea-test-utils'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { taskShareLogic } from './taskShareLogic'

jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn(async () => true) }))

const SPACES = [
    { id: 'space-me', name: 'Me', system_role: 'personal', channel_type: 'personal' },
    { id: 'space-team', name: 'Team', system_role: 'general', channel_type: 'public' },
]

describe('taskShareLogic', () => {
    let patchedChannel: string | null

    beforeEach(() => {
        patchedChannel = null
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': { results: SPACES },
                '/api/projects/:team_id/tasks/task-1/': () => [
                    200,
                    { id: 'task-1', channel: 'space-me', created_by: { uuid: 'creator' } },
                ],
            },
            patch: {
                '/api/projects/:team_id/tasks/task-1/': async ({ request }) => {
                    patchedChannel = ((await request.json()) as { channel: string }).channel
                    return [200, { id: 'task-1', channel: patchedChannel }]
                },
            },
        })
        initKeaTests()
    })

    it.each([
        ['public', 'space-me', 'space-team', true],
        ['private', 'space-team', 'space-me', false],
    ] as const)('making a task %s moves it to the matching space', async (visibility, from, to, copiesLink) => {
        const logic = taskShareLogic({ taskId: 'task-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadShareStateSuccess'])
        logic.actions.channelChanged(from)

        logic.actions.setVisibility(visibility)
        await expectLogic(logic)
            .toDispatchActions(['moveToSpace', 'channelChanged', 'visibilityChanged'])
            .toMatchValues({
                visibility,
                visibilityChanging: false,
            })

        expect(patchedChannel).toBe(to)
        if (copiesLink) {
            expect(copyToClipboard).toHaveBeenCalledWith(expect.stringContaining('/ai?task=task-1'), 'task link', {
                silent: true,
            })
        } else {
            expect(copyToClipboard).not.toHaveBeenCalled()
        }
        jest.mocked(copyToClipboard).mockClear()
    })
})
