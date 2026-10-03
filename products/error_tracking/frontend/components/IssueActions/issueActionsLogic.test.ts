import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

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

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

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

    it.each(['success', 'failure'] as const)('tracks a merge until %s', async (outcome) => {
        let settleMerge: () => void = () => undefined
        jest.spyOn(api.errorTracking, 'mergeInto').mockImplementation(
            () =>
                new Promise<{ content: string }>((resolve, reject) => {
                    settleMerge = () =>
                        outcome === 'success' ? resolve({ content: '' }) : reject(new Error('Merge failed'))
                })
        )

        logic.actions.mergeIssues(['target-issue', 'source-issue'])

        await expectLogic(logic).toMatchValues({ mergeInFlight: true })

        settleMerge()

        await expectLogic(logic)
            .toDispatchActions([outcome === 'success' ? 'mutationSuccess' : 'mutationFailure'])
            .toMatchValues({ mergeInFlight: false })
    })
})
