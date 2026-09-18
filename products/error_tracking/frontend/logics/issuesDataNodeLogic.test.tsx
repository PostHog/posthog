import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { ErrorTrackingIssue, ErrorTrackingQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesPartialUpdate } from '../generated/api'
import { issuesDataNodeLogic } from './issuesDataNodeLogic'

jest.mock('~/queries/query')
jest.mock('../generated/api', () => ({
    errorTrackingIssuesPartialUpdate: jest.fn(),
}))

const mockPerformQuery = jest.mocked(performQuery)
const mockErrorTrackingIssuesPartialUpdate = jest.mocked(errorTrackingIssuesPartialUpdate)

const query: ErrorTrackingQuery = {
    kind: NodeKind.ErrorTrackingQuery,
    dateRange: { date_from: '-7d' },
    orderBy: 'last_seen',
    volumeResolution: 1,
}
const issue = {
    id: 'issue-abc',
    name: 'TypeError: undefined is not a function',
    description: 'Something broke',
    library: 'web',
    status: 'active',
    severity: 'low',
    assignee: null,
    first_seen: '2026-05-01T10:00:00.000Z',
    last_seen: '2026-05-26T08:00:00.000Z',
    aggregations: {
        occurrences: 12,
        sessions: 4,
        users: 3,
        volume_buckets: [],
    },
} satisfies ErrorTrackingIssue

describe('issuesDataNodeLogic', () => {
    let logic: ReturnType<typeof issuesDataNodeLogic.build>
    let initialResults: ErrorTrackingIssue[]

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/error_tracking/spike_events': { results: [] },
            },
        })
        initKeaTests()
        mockPerformQuery.mockResolvedValue({ results: [] })
        mockErrorTrackingIssuesPartialUpdate.mockResolvedValue({} as never)
        logic = issuesDataNodeLogic({ key: 'error-tracking-issues-test', query })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDataSuccess'])
        initialResults = [issue]
        logic.actions.setResponse({ results: initialResults })
        mockPerformQuery.mockClear()
    })

    afterEach(() => logic.unmount())

    it('optimistically updates severity and reloads authoritative state after success', async () => {
        mockPerformQuery.mockResolvedValue({ results: [{ ...issue, severity: 'critical' }] })

        await expectLogic(logic, () => {
            logic.actions.updateIssueSeverity(issue.id, 'critical')
        })
            .toDispatchActions(['setResponse', 'mutationSuccess', 'reloadData', 'loadData'])
            .toFinishAllListeners()
            .toMatchValues({ results: [expect.objectContaining({ id: issue.id, severity: 'critical' })] })

        expect(mockPerformQuery.mock.calls[0][2]).toBe('force_blocking')
        expect(initialResults).toEqual([issue])
    })
})
