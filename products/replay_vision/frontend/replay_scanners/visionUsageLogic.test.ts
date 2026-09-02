import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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

describe('visionUsageLogic', () => {
    let logic: ReturnType<typeof visionUsageLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': { results: [makeScanner()], count: 1 },
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
})
