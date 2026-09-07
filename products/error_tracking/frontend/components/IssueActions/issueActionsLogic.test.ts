import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesMergeCreate, errorTrackingIssuesPartialUpdate } from '../../generated/api'
import { issueActionsLogic } from './issueActionsLogic'

jest.mock('../../generated/api', () => ({
    errorTrackingIssuesMergeCreate: jest.fn(),
    errorTrackingIssuesPartialUpdate: jest.fn(),
}))

const mockErrorTrackingIssuesPartialUpdate = jest.mocked(errorTrackingIssuesPartialUpdate)
const mockErrorTrackingIssuesMergeCreate = jest.mocked(errorTrackingIssuesMergeCreate)

describe('issueActionsLogic', () => {
    let logic: ReturnType<typeof issueActionsLogic.build>

    let errorToast: jest.SpyInstance
    let infoToast: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        mockErrorTrackingIssuesPartialUpdate.mockResolvedValue({} as never)
        mockErrorTrackingIssuesMergeCreate.mockResolvedValue({ success: true, target_issue_id: 'issue-one' })
        errorToast = jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
        infoToast = jest.spyOn(lemonToast, 'info').mockImplementation(jest.fn())
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

    it('reports the reason a merge failed', async () => {
        mockErrorTrackingIssuesMergeCreate.mockRejectedValue(
            new ApiError('Conflict', 409, undefined, { detail: 'These issues were merged already.' })
        )

        await expectLogic(logic, () => {
            logic.actions.mergeIssues(['issue-one', 'issue-two'])
        }).toDispatchActions(['mutationFailure'])

        expect(errorToast).toHaveBeenCalledWith('Could not merge these issues. These issues were merged already.')
    })

    it('follows the issue the merge wrote into', async () => {
        mockErrorTrackingIssuesMergeCreate.mockResolvedValue({ success: true, target_issue_id: 'issue-two' })

        await expectLogic(logic, () => {
            logic.actions.mergeIssues(['issue-one', 'issue-two', 'issue-three'])
        }).toDispatchActions([
            {
                type: logic.actionTypes.mergeIssuesSuccess,
                payload: { primaryId: 'issue-one', targetId: 'issue-two', merged: true },
            },
        ])

        expect(infoToast).not.toHaveBeenCalled()
    })

    it('says so when a merge moved nothing', async () => {
        mockErrorTrackingIssuesMergeCreate.mockResolvedValue({ success: false, target_issue_id: 'issue-two' })

        await expectLogic(logic, () => {
            logic.actions.mergeIssues(['issue-one', 'issue-two'])
        }).toDispatchActions(['mergeIssuesSuccess'])

        expect(infoToast).toHaveBeenCalledWith(
            'These issues were merged already. The list now shows the current issues.'
        )
    })
})
