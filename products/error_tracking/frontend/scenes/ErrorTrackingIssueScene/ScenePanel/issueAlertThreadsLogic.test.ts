import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { errorTrackingAlertsThreadsRetrieve } from '../../../generated/api'
import { issueAlertThreadsLogic } from './issueAlertThreadsLogic'

jest.mock('../../../generated/api', () => ({
    errorTrackingAlertsThreadsRetrieve: jest.fn(),
}))

const mockThreads = jest.mocked(errorTrackingAlertsThreadsRetrieve)

describe('issueAlertThreadsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockThreads.mockResolvedValue([{ id: 't1', alert_name: 'Production errors' }] as never)
    })

    it('loads the threads for its issue on mount', async () => {
        const logic = issueAlertThreadsLogic({ issueId: 'issue-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadThreads', 'loadThreadsSuccess'])
        expect(mockThreads).toHaveBeenCalledWith(expect.any(String), { issue_id: 'issue-1' })
        expect(logic.values.threads.map((t) => t.id)).toEqual(['t1'])
        logic.unmount()
    })
})
