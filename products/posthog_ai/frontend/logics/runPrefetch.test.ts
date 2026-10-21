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
})
