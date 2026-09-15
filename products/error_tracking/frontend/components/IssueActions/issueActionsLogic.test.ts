import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

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
    let successToast: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        mockErrorTrackingIssuesPartialUpdate.mockResolvedValue({} as never)
        mockErrorTrackingIssuesMergeCreate.mockResolvedValue({ success: true, target_issue_id: 'issue-one' })
        errorToast = jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
        infoToast = jest.spyOn(lemonToast, 'info').mockImplementation(jest.fn())
        successToast = jest.spyOn(lemonToast, 'success').mockImplementation(jest.fn())
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

    it('reports a failed unmerge once, in the words the fingerprints scene uses', async () => {
        jest.spyOn(api.errorTracking, 'split').mockRejectedValue(
            new ApiError('Conflict', 409, undefined, { detail: 'Issue fingerprints changed before merge.' })
        )

        await expectLogic(logic, () => {
            logic.actions.splitIssue('issue-one', [{ fingerprint: 'fingerprint-one' }])
        }).toDispatchActions(['mutationFailure'])

        expect(errorToast).toHaveBeenCalledTimes(1)
        expect(errorToast).toHaveBeenCalledWith(
            'Could not unmerge this fingerprint. Issue fingerprints changed before merge.'
        )
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

    it('merges against the active environment, not its project', async () => {
        // Every environment a project gains after its first has an id that differs from the project id.
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 3117 })

        await expectLogic(logic, () => {
            logic.actions.mergeIssues(['issue-one', 'issue-two'])
        }).toDispatchActions(['mergeIssuesSuccess'])

        expect(mockErrorTrackingIssuesMergeCreate).toHaveBeenCalledWith('3117', 'issue-one', { ids: ['issue-two'] })
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

    it.each<[string, boolean]>([
        ['announces the cohort once it exists', true],
        ['does not announce a cohort it failed to create', false],
    ])('%s', async (_name, assignSucceeds) => {
        jest.spyOn(api.cohorts, 'create').mockResolvedValue({ id: 7 } as never)
        const assign = jest.spyOn(api.errorTracking, 'assignCohort')
        if (assignSucceeds) {
            assign.mockResolvedValue({ id: 'cohort-7' })
        } else {
            assign.mockRejectedValue(new ApiError('Server error', 500))
        }

        await expectLogic(logic, () => {
            logic.actions.createIssueCohort('issue-one', 'Impacted users', 'a description')
        }).toDispatchActions([assignSucceeds ? 'mutationSuccess' : 'mutationFailure'])

        expect(successToast).toHaveBeenCalledTimes(assignSucceeds ? 1 : 0)
        expect(errorToast).toHaveBeenCalledTimes(assignSucceeds ? 0 : 1)
    })
})
