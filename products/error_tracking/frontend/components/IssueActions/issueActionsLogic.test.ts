import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesBulkCreate, errorTrackingIssuesPartialUpdate } from '../../generated/api'
import { issueActionsLogic } from './issueActionsLogic'

jest.mock('../../generated/api', () => ({
    errorTrackingIssuesBulkCreate: jest.fn(),
    errorTrackingIssuesPartialUpdate: jest.fn(),
}))

const mockErrorTrackingIssuesBulkCreate = jest.mocked(errorTrackingIssuesBulkCreate)
const mockErrorTrackingIssuesPartialUpdate = jest.mocked(errorTrackingIssuesPartialUpdate)

function pendingRequest<T>(): { promise: Promise<T>; settle: (outcome: 'success' | 'failure') => void } {
    let settle: (outcome: 'success' | 'failure') => void = () => undefined
    const promise = new Promise<T>((resolve, reject) => {
        settle = (outcome) => (outcome === 'success' ? resolve({} as T) : reject(new Error('Request failed')))
    })
    return { promise, settle }
}

describe('issueActionsLogic', () => {
    let logic: ReturnType<typeof issueActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockErrorTrackingIssuesPartialUpdate.mockResolvedValue({} as never)
        mockErrorTrackingIssuesBulkCreate.mockResolvedValue({} as never)
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

    it('resolves issues in bulk without a mode, so the server default applies', async () => {
        await expectLogic(logic, () => {
            logic.actions.resolveIssues(['issue-a', 'issue-b'])
        }).toDispatchActions(['mutationSuccess'])

        expect(mockErrorTrackingIssuesBulkCreate).toHaveBeenCalledWith(expect.any(String), {
            action: 'set_status',
            ids: ['issue-a', 'issue-b'],
            status: 'resolved',
        })
    })

    describe.each([
        {
            mutation: 'a merge',
            stall: (promise: Promise<unknown>) =>
                jest.spyOn(api.errorTracking, 'mergeInto').mockReturnValue(promise as Promise<{ content: string }>),
            start: () => issueActionsLogic().actions.mergeIssues(['target-issue', 'source-issue']),
            inFlight: { mergeInFlight: true },
            settled: { mergeInFlight: false },
        },
        {
            mutation: 'a status change',
            stall: (promise: Promise<unknown>) =>
                mockErrorTrackingIssuesPartialUpdate.mockReturnValue(promise as never),
            start: () => issueActionsLogic().actions.updateIssueStatus('issue-abc', 'resolved'),
            inFlight: { statusUpdateInFlightIds: ['issue-abc'] },
            settled: { statusUpdateInFlightIds: [] },
        },
    ])('tracks $mutation', ({ stall, start, inFlight, settled }) => {
        it.each(['success', 'failure'] as const)('until %s', async (outcome) => {
            const request = pendingRequest<unknown>()
            stall(request.promise)

            start()

            await expectLogic(logic).toMatchValues(inFlight)

            request.settle(outcome)

            await expectLogic(logic)
                .toDispatchActions([outcome === 'success' ? 'mutationSuccess' : 'mutationFailure'])
                .toMatchValues(settled)
        })
    })
})
