import type { HogFlowBatchJobApi, HogFlowMinimalApi } from 'products/workflows/frontend/generated/api.schemas'

import { getBroadcastStatus } from './broadcastsLogic'

const flow = (status: string): HogFlowMinimalApi => ({ status }) as unknown as HogFlowMinimalApi
const withJob = (status: string): { latestBatchJob: HogFlowBatchJobApi; totals: Record<string, number> } => ({
    latestBatchJob: { status } as HogFlowBatchJobApi,
    totals: {},
})

describe('getBroadcastStatus', () => {
    it.each([
        ['a draft, whatever its runs say', flow('draft'), withJob('completed'), 'draft'],
        ['an archived broadcast', flow('archived'), withJob('completed'), 'archived'],
        ['a run still going', flow('active'), withJob('active'), 'sending'],
        ['a run that finished', flow('active'), withJob('completed'), 'sent'],
        // A terminal run used to fall through to the no-run fallback and read as "scheduled",
        // telling the sender another send was pending when nothing was coming.
        ['a run that failed', flow('active'), withJob('failed'), 'failed'],
        ['a run that was cancelled', flow('active'), withJob('cancelled'), 'failed'],
        ['no run yet', flow('active'), undefined, 'scheduled'],
    ])('reads %s as %s', (_name, broadcast, details, expected) => {
        expect(getBroadcastStatus(broadcast, details)).toBe(expected)
    })
})
