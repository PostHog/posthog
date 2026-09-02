import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeQuota } from '../utils/quotaTestUtils'
import { ReplayScanner } from './types'
import { visionUsageLogic } from './visionUsageLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

function makeScanner(overrides: Partial<ReplayScanner> = {}): ReplayScanner {
    const base = {
        id: 'a',
        name: 'Confused checkout',
        description: '',
        tags: [],
        enabled: true,
        sampling_rate: 0.1,
        query: null,
        provider: 'google',
        model: 'gemini-3.7-flash',
        emits_signals: false,
        scanner_version: 1,
        last_swept_at: '2026-05-12T00:00:00Z',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
        created_by: null,
        scanner_type: 'monitor',
        scanner_config: { prompt: 'Did the user struggle?' },
    }
    return { ...base, ...overrides } as ReplayScanner
}

const PERIOD_A = '2026-05-01T00:00:00Z'
const PERIOD_A_END = '2026-06-01T00:00:00Z'
const PERIOD_B = '2026-06-01T00:00:00Z'

describe('visionUsageLogic', () => {
    let logic: ReturnType<typeof visionUsageLogic.build>
    let spendSeriesRequests = 0

    beforeEach(() => {
        spendSeriesRequests = 0
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': { results: [makeScanner()], count: 1 },
                '/api/projects/:team/vision/quota/spend_series/': () => {
                    spendSeriesRequests += 1
                    return [200, { period_start: PERIOD_A, period_end: PERIOD_A_END, days: [] }]
                },
            },
            patch: {
                '/api/projects/:team/vision/scanners/:id/': () => [200, {}],
            },
        })
        initKeaTests()
        jest.clearAllMocks()
        logic = visionUsageLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('toggleScannerEnabled', () => {
        it('optimistically flips the row and marks it in-flight, then clears in-flight on success', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.toggleScannerEnabled(makeScanner({ enabled: true }))
            }).toMatchValues({
                usageScanners: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: false })]),
                togglingScannerIds: ['a'],
            })

            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({
                    usageScanners: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: false })]),
                    togglingScannerIds: [],
                })
            expect(lemonToast.success).toHaveBeenCalledWith('Scanner disabled')
        })

        it('rolls the row back and clears in-flight when the request fails', async () => {
            useMocks({
                patch: {
                    '/api/projects/:team/vision/scanners/:id/': () => [400, { detail: 'nope' }],
                },
            })
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.toggleScannerEnabled(makeScanner({ enabled: true }))
            })
                .toFinishAllListeners()
                .toMatchValues({
                    usageScanners: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: true })]),
                    togglingScannerIds: [],
                })
            expect(lemonToast.error).toHaveBeenCalledWith('Failed to disable scanner: nope')
        })
    })

    describe('spend series', () => {
        it('loads once per billing period, not on every quota refetch', async () => {
            await expectLogic(logic).toFinishAllListeners()
            const quotaA = makeQuota({ period_start: PERIOD_A, period_end: PERIOD_A_END })

            await expectLogic(logic, () => {
                logic.actions.loadQuotaSuccess(quotaA)
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.loadQuotaSuccess({ ...quotaA, credits_used: 42 })
            }).toFinishAllListeners()
            expect(spendSeriesRequests).toBe(1)

            await expectLogic(logic, () => {
                logic.actions.loadQuotaSuccess(makeQuota({ period_start: PERIOD_B }))
            }).toFinishAllListeners()
            expect(spendSeriesRequests).toBe(2)
        })

        it('does not retry a failed period on the next quota refetch, but does on request', async () => {
            // Let the mount's successful load settle before swapping in the failing mock.
            await expectLogic(logic).toFinishAllListeners()
            logic.unmount()
            spendSeriesRequests = 0
            useMocks({
                get: {
                    '/api/projects/:team/vision/quota/spend_series/': () => {
                        spendSeriesRequests += 1
                        return [500, { detail: 'boom' }]
                    },
                },
            })
            logic = visionUsageLogic()
            logic.mount()
            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({ spendSeries: null, spendSeriesFailed: true })
            const quotaA = makeQuota({ period_start: PERIOD_A, period_end: PERIOD_A_END })

            await expectLogic(logic, () => {
                logic.actions.loadQuotaSuccess(quotaA)
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.loadQuotaSuccess({ ...quotaA, credits_used: 7 })
            }).toFinishAllListeners()
            expect(spendSeriesRequests).toBe(1)

            await expectLogic(logic, () => {
                logic.actions.loadSpendSeries()
            }).toFinishAllListeners()
            expect(spendSeriesRequests).toBe(2)
        })
    })
})
