import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesPartialUpdate } from '../../generated/api'
import { issueActionsLogic } from './issueActionsLogic'

jest.mock('../../generated/api', () => ({
    errorTrackingIssuesPartialUpdate: jest.fn(),
}))

const mockErrorTrackingIssuesPartialUpdate = jest.mocked(errorTrackingIssuesPartialUpdate)

describe('issueActionsLogic', () => {
    let logic: ReturnType<typeof issueActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockErrorTrackingIssuesPartialUpdate.mockResolvedValue({} as never)
        logic = issueActionsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('updates issue severity and clears its loading state', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateIssueSeverity('issue-abc', 'critical')
        })
            .toDispatchActions(['finishIssueSeverityUpdate'])
            .toMatchValues({ severityUpdateInFlightIds: [] })

        expect(mockErrorTrackingIssuesPartialUpdate).toHaveBeenCalledWith(expect.any(String), 'issue-abc', {
            severity: 'critical',
        })
    })
})
