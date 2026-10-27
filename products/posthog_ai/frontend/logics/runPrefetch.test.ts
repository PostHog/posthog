import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { tasksRunsRetrieve } from 'products/tasks/frontend/generated/api'

import { turnSuggestionsStateRetrieve } from '../generated/api'
import { prefetchRunStream } from './runPrefetch'
import { runStreamLogic } from './runStreamLogic'

jest.mock('../generated/api', () => ({ turnSuggestionsStateRetrieve: jest.fn() }))
jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksRunsRetrieve: jest.fn(),
    tasksRunsCommandCreate: jest.fn(),
    tasksRunsStreamTokenRetrieve: jest.fn(),
}))

describe('prefetchRunStream', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(tasksRunsRetrieve)
            .mockReset()
            .mockResolvedValue({ status: 'completed', state: {} } as any)
        jest.mocked(turnSuggestionsStateRetrieve).mockResolvedValue({ muted: false, resolved_turns: [] })
        jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([])
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('loads a hovered run once and keeps it mounted for the click', async () => {
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 997 } as any)
        prefetchRunStream('task-1', 'run-1', null)
        prefetchRunStream('task-1', 'run-1', null)
        const logic = runStreamLogic.findMounted({ streamKey: 'run-1' })
        await expectLogic(logic!).toFinishAllListeners()

        expect(logic?.values.bootstrappedRunId).toBe('run-1')
        expect(tasksRunsRetrieve).toHaveBeenCalledTimes(1)
    })

    it('leaves a stream that already serves a follow-up run alone', async () => {
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 997 } as any)
        const continued = runStreamLogic({ streamKey: 'run-a' })
        continued.mount()
        continued.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-b' })
        await expectLogic(continued).toFinishAllListeners()

        prefetchRunStream('task-1', 'run-a', null)
        await expectLogic(continued).toFinishAllListeners()

        expect(continued.values.bootstrappedRunId).toBe('run-b')
        expect(tasksRunsRetrieve).toHaveBeenCalledTimes(1)
    })

    it('skips a run that a retained chat already streams under another key', async () => {
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 997 } as any)
        const continued = runStreamLogic({ streamKey: 'run-a' })
        continued.mount()
        continued.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-b' })
        await expectLogic(continued).toFinishAllListeners()

        prefetchRunStream('task-1', 'run-b', null)

        expect(runStreamLogic.findMounted({ streamKey: 'run-b' })).toBeNull()
        expect(tasksRunsRetrieve).toHaveBeenCalledTimes(1)
    })

    it('skips a Pi task while Pi runs are not shown on the web', () => {
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 997 } as any)

        prefetchRunStream('task-1', 'run-pi', 'pi')

        expect(runStreamLogic.findMounted({ streamKey: 'run-pi' })).toBeNull()
        expect(tasksRunsRetrieve).not.toHaveBeenCalled()
    })

    it('keeps the most recently hovered row when a third row is hovered', async () => {
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 997 } as any)

        for (const runId of ['run-a', 'run-b', 'run-a', 'run-c']) {
            prefetchRunStream('task-1', runId, null)
            await expectLogic(runStreamLogic({ streamKey: runId })).toFinishAllListeners()
        }

        expect(runStreamLogic.findMounted({ streamKey: 'run-a' })).not.toBeNull()
        expect(runStreamLogic.findMounted({ streamKey: 'run-b' })).toBeNull()
    })
})
