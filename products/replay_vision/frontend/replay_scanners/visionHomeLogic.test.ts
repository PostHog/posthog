import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { addProductIntent } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { visionScannersListLogic } from '../logics/visionScannersListLogic'
import { STATUS_POLL_MS } from './scannerStatus'
import { REPLAY_VISION_INTENT_DWELL_MS, visionHomeLogic } from './visionHomeLogic'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

describe('visionHomeLogic', () => {
    let logic: ReturnType<typeof visionHomeLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': {
                    results: [{ id: 'scanner-a', name: 'A', created_at: '2026-01-01T00:00:00Z' }],
                    next: null,
                },
                '/api/projects/:team/vision/scanners/highlight_feed/': {
                    results: [],
                    highlight_count: 3,
                    highlight_counts_by_scanner: { 'scanner-a': 3 },
                    observation_count: 9,
                },
            },
        })
        initKeaTests()
        ;(addProductIntent as jest.Mock).mockClear()
        logic = visionHomeLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['', 'all'],
        ['?tab=highlights', 'all'],
        ['?tab=scanners', 'all'],
        ['?tab=usage', 'usage'],
        ['?scanner=scanner-a', 'scanner-a'],
        ['?scanner=deleted-scanner', 'all'],
    ])('reads %s as the %s view', async (query, expected) => {
        router.actions.push(`${urls.replayVision()}${query}`)
        logic.mount()
        await expectLogic(visionScannersListLogic).toDispatchActions(['loadScannersSuccess'])
        expect(logic.values.view).toBe(expected)
    })

    // The URL changes a moment before the scene does, so reading it then would flash the default feed.
    it.each([
        ['the edit page', urls.replayVisionScannerConfigure('scanner-a')],
        ['the scanner page', `${urls.replayVision('scanner-a')}?tab=observations`],
    ])('keeps the scanner view while the URL moves to %s', async (_, destination) => {
        router.actions.push(`${urls.replayVision()}?scanner=scanner-a`)
        logic.mount()
        await expectLogic(visionScannersListLogic).toDispatchActions(['loadScannersSuccess'])
        router.actions.push(destination)
        expect(logic.values.view).toBe('scanner-a')
    })

    it('reloads the scanners while one is starting', async () => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': {
                    results: [
                        {
                            id: 'scanner-a',
                            name: 'A',
                            enabled: true,
                            sweep_interval_minutes: 5,
                            created_at: new Date().toISOString(),
                            last_swept_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
                        },
                    ],
                    next: null,
                },
            },
        })
        // Only intervals are faked, so the mocked requests still resolve on their own.
        jest.useFakeTimers({ doNotFake: ['nextTick', 'queueMicrotask', 'setImmediate', 'setTimeout', 'Date'] })
        try {
            logic.mount()
            await expectLogic(visionScannersListLogic).toDispatchActions(['loadScannersSuccess'])
            expect(logic.values.scannerStatuses['scanner-a'].kind).toBe('starting')
            jest.advanceTimersByTime(STATUS_POLL_MS)
            await expectLogic(visionScannersListLogic).toDispatchActions(['loadScanners'])
        } finally {
            jest.useRealTimers()
        }
    })

    describe('shallow product intent', () => {
        // One ProductIntent row per team starts its 30-day activation clock, so a bounce must not register.
        beforeEach(() => {
            jest.useFakeTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('registers only once the reader has stayed past the dwell time', () => {
            logic.mount()
            jest.advanceTimersByTime(REPLAY_VISION_INTENT_DWELL_MS - 1)
            expect(addProductIntent).not.toHaveBeenCalled()
            jest.advanceTimersByTime(1)
            jest.advanceTimersByTime(REPLAY_VISION_INTENT_DWELL_MS * 3)
            expect(addProductIntent).toHaveBeenCalledTimes(1)
            expect(addProductIntent).toHaveBeenCalledWith({
                product_type: ProductKey.REPLAY_VISION,
                intent_context: ProductIntentContext.REPLAY_VISION_VIEWED,
            })
        })

        it('does not register when the reader leaves before the dwell time', () => {
            logic.mount()
            logic.unmount()
            jest.advanceTimersByTime(REPLAY_VISION_INTENT_DWELL_MS * 2)
            expect(addProductIntent).not.toHaveBeenCalled()
            logic.mount()
        })
    })
})
