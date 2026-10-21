import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { hogFlowsBatchJobsList, hogFlowsList } from 'products/workflows/frontend/generated/api'

import { broadcastPreviousSendLogic } from './broadcastPreviousSendLogic'
import { loadRunMetricTotals } from './broadcastsLogic'

jest.mock('products/workflows/frontend/generated/api', () => ({
    hogFlowsList: jest.fn(),
    hogFlowsBatchJobsList: jest.fn(),
}))
jest.mock('./broadcastsLogic', () => ({ loadRunMetricTotals: jest.fn() }))

const mockList = jest.mocked(hogFlowsList)
const mockJobs = jest.mocked(hogFlowsBatchJobsList)
const mockTotals = jest.mocked(loadRunMetricTotals)

describe('broadcastPreviousSendLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    it.each([
        {
            case: 'nothing went out about the record',
            flows: [],
            jobs: [],
            totals: {} as Record<string, number>,
            expected: null,
            sentCount: null,
        },
        {
            case: 'a broadcast about the record was sent',
            flows: [{ id: 'flow-1' }],
            jobs: [{ id: 'job-1', created_at: '2026-10-12T09:00:00Z' }],
            totals: { email_sent: 12 },
            expected: { broadcastId: 'flow-1', latestJob: { id: 'job-1', created_at: '2026-10-12T09:00:00Z' } },
            sentCount: 12,
        },
        {
            case: 'a broadcast about the record is scheduled and has not run',
            flows: [{ id: 'flow-1' }],
            jobs: [],
            totals: {} as Record<string, number>,
            expected: { broadcastId: 'flow-1', latestJob: null },
            sentCount: null,
        },
    ])('finds the earlier broadcast when $case', async ({ flows, jobs, totals, expected, sentCount }) => {
        mockList.mockResolvedValue({ results: flows } as never)
        mockJobs.mockResolvedValue(jobs as never)
        mockTotals.mockResolvedValue(totals)

        const logic = broadcastPreviousSendLogic({ sourceRecord: 'early_access:feature-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockList.mock.calls[0][1]).toEqual({
            source_record: 'early_access:feature-1',
            broadcast_status: 'scheduled,sending,sent',
            limit: 1,
        })
        expect(logic.values.previousSend).toEqual(expected)
        expect(logic.values.sentCount).toEqual(sentCount)
        logic.unmount()
    })
})
