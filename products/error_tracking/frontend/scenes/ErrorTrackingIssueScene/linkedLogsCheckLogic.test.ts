import { waitFor } from '@testing-library/react'

import { performQuery } from '~/queries/query'
import { ErrorTrackingIssueEventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

import { AUTO_CHECK_LIMIT, linkedLogsCheckLogic } from './linkedLogsCheckLogic'

jest.mock('~/queries/query')

const mockPerformQuery = jest.mocked(performQuery)

const query = setLatestVersionsOnQuery<ErrorTrackingIssueEventsQuery>({
    kind: NodeKind.ErrorTrackingIssueEventsQuery,
    issueId: 'issue',
    source: setLatestVersionsOnQuery({ kind: NodeKind.EventsQuery, select: ['*', 'timestamp', 'person'] }),
    requiredLinkedData: ['logs'],
})

const PAGE_CHECKED_COUNT = 2_000

describe('linkedLogsCheckLogic', () => {
    let logic: ReturnType<typeof linkedLogsCheckLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockPerformQuery.mockReset()
    })
    afterEach(() => logic?.unmount())

    it('checks older pages until it reaches the limit, then continues from the last page when asked', async () => {
        const emptyPages = AUTO_CHECK_LIMIT / PAGE_CHECKED_COUNT
        for (let page = 1; page <= emptyPages; page++) {
            mockPerformQuery.mockResolvedValueOnce({
                results: [],
                hasMore: true,
                nextCursor: `cursor-${page}`,
                checkedCount: PAGE_CHECKED_COUNT,
            })
        }
        logic = linkedLogsCheckLogic({ query, queryKey: 'linked-logs-check-test' })
        logic.mount()

        await waitFor(() => expect(logic.values.status).toEqual('paused'))
        expect(mockPerformQuery).toHaveBeenCalledTimes(emptyPages)
        expect(logic.values.checkedCount).toEqual(AUTO_CHECK_LIMIT)

        mockPerformQuery.mockResolvedValueOnce({
            results: [[{ uuid: 'exception', properties: {} }, '2026-10-20T00:00:00Z', { distinct_id: 'user' }]],
            hasMore: false,
            checkedCount: 300,
        })
        logic.actions.checkOlderExceptions()

        await waitFor(() => expect(logic.values.items).toHaveLength(1))
        expect(mockPerformQuery).toHaveBeenCalledTimes(emptyPages + 1)
        expect(mockPerformQuery.mock.lastCall?.[0]).toMatchObject({ source: { before: `cursor-${emptyPages}` } })
        expect(logic.values.status).toBeNull()
    })
})
