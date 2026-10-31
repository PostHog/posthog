import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { hogFlowsBatchJobsList, hogFlowsList, hogFlowsSchedulesList } from 'products/workflows/frontend/generated/api'

import { broadcastPreviousSendLogic } from './broadcastPreviousSendLogic'
import { loadRunMetricTotals } from './broadcastsLogic'

jest.mock('products/workflows/frontend/generated/api', () => ({
    hogFlowsList: jest.fn(),
    hogFlowsBatchJobsList: jest.fn(),
    hogFlowsSchedulesList: jest.fn(),
}))
jest.mock('./broadcastsLogic', () => ({ loadRunMetricTotals: jest.fn() }))

const mockList = jest.mocked(hogFlowsList)
const mockJobs = jest.mocked(hogFlowsBatchJobsList)
const mockSchedules = jest.mocked(hogFlowsSchedulesList)
const mockTotals = jest.mocked(loadRunMetricTotals)

const completed = { id: 'job-1', status: 'completed', created_at: '2026-10-12T09:00:00Z' }

describe('broadcastPreviousSendLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockSchedules.mockResolvedValue([])
        mockTotals.mockResolvedValue({ email_sent: 12 })
    })

    it.each([
        { case: 'nothing went out about the record', flows: [], jobs: {}, expected: null, sentCount: null },
        {
            case: 'only a draft exists',
            flows: [{ id: 'draft-1', status: 'draft' }],
            jobs: {},
            expected: null,
            sentCount: null,
        },
        {
            case: 'an archived broadcast already sent',
            flows: [{ id: 'flow-1', status: 'archived' }],
            jobs: { 'flow-1': [completed] },
            expected: { broadcastId: 'flow-1', state: 'sent', job: completed },
            sentCount: 12,
        },
        {
            case: 'a run is queued but nobody got the email yet',
            flows: [{ id: 'flow-1', status: 'active' }],
            jobs: { 'flow-1': [{ id: 'job-2', status: 'queued', created_at: '2026-10-20T09:00:00Z' }] },
            expected: { broadcastId: 'flow-1', state: 'scheduled', job: null },
            sentCount: null,
        },
        {
            case: 'a newer broadcast is sending and an older one already sent',
            flows: [
                { id: 'flow-2', status: 'active' },
                { id: 'flow-1', status: 'active' },
            ],
            jobs: { 'flow-2': [{ id: 'job-3', status: 'active' }], 'flow-1': [completed] },
            expected: { broadcastId: 'flow-1', state: 'sent', job: completed },
            sentCount: 12,
        },
        {
            case: 'a failed run is the only history',
            flows: [{ id: 'flow-1', status: 'active' }],
            jobs: { 'flow-1': [{ id: 'job-4', status: 'failed' }] },
            expected: null,
            sentCount: null,
        },
    ])('reports the earlier broadcast when $case', async ({ flows, jobs, expected, sentCount }) => {
        mockList.mockResolvedValue({ results: flows } as never)
        mockJobs.mockImplementation(async (_, id) => ((jobs as Record<string, unknown[]>)[id] ?? []) as never)

        const logic = broadcastPreviousSendLogic({ sourceRecord: 'early_access:feature-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockList.mock.calls[0][1]).toEqual({ source_record: 'early_access:feature-1', limit: 5 })
        expect(logic.values.previousSend).toEqual(expected)
        expect(logic.values.sentCount).toEqual(sentCount)
        logic.unmount()
    })

    it('reports a broadcast scheduled for later that has not run', async () => {
        mockList.mockResolvedValue({ results: [{ id: 'flow-1', status: 'active' }] } as never)
        mockJobs.mockResolvedValue([])
        mockSchedules.mockResolvedValue([{ status: 'active' }] as never)

        const logic = broadcastPreviousSendLogic({ sourceRecord: 'cohort:7' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.previousSend).toEqual({ broadcastId: 'flow-1', state: 'scheduled', job: null })
        logic.unmount()
    })
})
