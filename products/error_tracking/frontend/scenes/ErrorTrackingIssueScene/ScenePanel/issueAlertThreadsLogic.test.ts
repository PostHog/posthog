import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { issueActionsLogic } from '../../../components/IssueActions/issueActionsLogic'
import { errorTrackingAlertsThreadsRetrieve } from '../../../generated/api'
import { ErrorTrackingAlertThreadApi } from '../../../generated/api.schemas'
import { issueAlertThreadsLogic } from './issueAlertThreadsLogic'

jest.mock('../../../generated/api', () => ({
    errorTrackingAlertsThreadsRetrieve: jest.fn(),
}))

const mockThreads = jest.mocked(errorTrackingAlertsThreadsRetrieve)

const THREAD: ErrorTrackingAlertThreadApi = {
    id: 't1',
    alert_id: 'a1',
    alert_name: 'Production errors',
    channel_type: 'slack',
    channel: 'C0123',
    channel_name: '#alerts',
    external_url: 'https://app.slack.com/client/T0WORK/C0123/thread/C0123-1.2',
    root_headline: '🔴 New issue',
    last_error: '',
    consecutive_failures: 0,
    created_at: '2026-09-02T10:00:00Z',
    updated_at: '2026-09-02T10:00:00Z',
}

describe('issueAlertThreadsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockThreads.mockResolvedValue([THREAD])
    })

    it('loads the threads for its issue on mount', async () => {
        const logic = issueAlertThreadsLogic({ issueId: 'issue-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadThreads', 'loadThreadsSuccess'])
        expect(mockThreads).toHaveBeenCalledWith(expect.any(String), { issue_id: 'issue-1' })
        expect(logic.values.threads.map((t) => t.id)).toEqual(['t1'])
        logic.unmount()
    })

    it('reloads after an issue mutation so new replies and threads show up', async () => {
        const logic = issueAlertThreadsLogic({ issueId: 'issue-3' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadThreadsSuccess'])
        const callsBefore = mockThreads.mock.calls.length

        await expectLogic(logic, () =>
            issueActionsLogic.actions.mutationSuccess('updateIssueStatus')
        ).toDispatchActions(['mutationSuccess', 'loadThreads', 'loadThreadsSuccess'])
        expect(mockThreads.mock.calls.length).toBeGreaterThan(callsBefore)
        logic.unmount()
    })

    it('keeps a failed load apart from an empty list', async () => {
        mockThreads.mockReset().mockRejectedValue(new Error('boom'))
        const logic = issueAlertThreadsLogic({ issueId: 'issue-2' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadThreadsFailure'])
        expect(logic.values.threadsLoaded).toBe(false)
        expect(logic.values.loadError).toBeTruthy()
        logic.unmount()
    })
})
