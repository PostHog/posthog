import { actions, kea, key, path, props, reducers } from 'kea'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { tasksRunsRetrieve } from 'products/tasks/frontend/generated/api'

import { turnSuggestionsStateRetrieve } from '../generated/api'
import { RETAINED_RUN_STREAMS, resolveRunStreamKey, retainMountedLogic } from './retainedLogics'
import { runStreamLogic } from './runStreamLogic'

jest.mock('../generated/api', () => ({ turnSuggestionsStateRetrieve: jest.fn() }))
jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksRunsRetrieve: jest.fn(),
    tasksRunsCommandCreate: jest.fn(),
    tasksRunsStreamTokenRetrieve: jest.fn(),
}))

const counterLogic = kea([
    props({} as { id: string }),
    key((props) => props.id),
    path((id) => ['test', 'retainedLogics', 'counter', id]),
    actions({ increment: true }),
    reducers({ count: [0, { increment: (state: number) => state + 1 }] }),
])

describe('retainedLogics', () => {
    beforeEach(() => {
        initKeaTests()
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 997 } as any)
        jest.mocked(tasksRunsRetrieve)
            .mockReset()
            .mockResolvedValue({ status: 'completed', state: {} } as any)
        jest.mocked(turnSuggestionsStateRetrieve).mockResolvedValue({ muted: false, resolved_turns: [] })
        jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([])
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('keeps the logic and its state after its holder unmounts, and evicts the oldest past the limit', () => {
        const holderUnmount = counterLogic({ id: 'a' }).mount()
        expect(retainMountedLogic('test', 'a', counterLogic({ id: 'a' }), 2)).toBe(false)
        counterLogic({ id: 'a' }).actions.increment()
        holderUnmount()

        expect(counterLogic.findMounted({ id: 'a' })?.values.count).toBe(1)
        expect(retainMountedLogic('test', 'a', counterLogic({ id: 'a' }), 2)).toBe(true)

        retainMountedLogic('test', 'b', counterLogic({ id: 'b' }), 2)
        retainMountedLogic('test', 'a', counterLogic({ id: 'a' }), 2)
        retainMountedLogic('test', 'c', counterLogic({ id: 'c' }), 2)

        expect(counterLogic.findMounted({ id: 'b' })).toBeNull()
        expect(counterLogic.findMounted({ id: 'a' })?.values.count).toBe(1)
        expect(counterLogic.findMounted({ id: 'c' })).not.toBeNull()
    })

    async function streamServing(streamKey: string, runId: string): Promise<() => void> {
        const logic = runStreamLogic({ streamKey })
        const unmount = logic.mount()
        logic.actions.bootstrapRun({ taskId: 'task-1', runId })
        await expectLogic(logic).toFinishAllListeners()
        return unmount
    }

    it.each([
        { name: 'no key resolves to the continuation alias', streamKey: undefined, expected: 'run-a' },
        { name: 'the run id resolves to the continuation alias', streamKey: 'run-b', expected: 'run-a' },
        { name: 'an explicit other key is kept', streamKey: 'client-key', expected: 'client-key' },
    ])('$name', async ({ streamKey, expected }) => {
        await streamServing('run-a', 'run-b')

        expect(resolveRunStreamKey('run-b', streamKey)).toBe(expected)
    })

    it('finds an alias that retention evicted while another surface keeps it mounted', async () => {
        const panelUnmount = await streamServing('run-a', 'run-b')
        retainMountedLogic(RETAINED_RUN_STREAMS, 'run-a', runStreamLogic({ streamKey: 'run-a' }), 1)
        retainMountedLogic(RETAINED_RUN_STREAMS, 'run-c', counterLogic({ id: 'run-c' }), 1)

        expect(resolveRunStreamKey('run-b', undefined)).toBe('run-a')

        panelUnmount()
        expect(resolveRunStreamKey('run-b', undefined)).toBeUndefined()
    })

    it('drops an instance from the registry when it streams a run it did not bootstrap', async () => {
        await streamServing('conversation-1', 'run-a')
        runStreamLogic({ streamKey: 'conversation-1' }).actions.openSseForRun({ taskId: 'task-1', runId: 'run-b' })

        expect(resolveRunStreamKey('run-a', undefined)).toBeUndefined()
        expect(resolveRunStreamKey('run-b', undefined)).toBeUndefined()
    })
})
