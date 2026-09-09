import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayScannersLogic } from './replayScannersLogic'
import { scannerHighlightsLogic } from './scannerHighlightsLogic'

describe('scannerHighlightsLogic', () => {
    let logic: ReturnType<typeof scannerHighlightsLogic.build>
    let recentSpy: jest.Mock

    const scannerRow = (id: string): Record<string, any> => ({
        id,
        name: `scanner-${id}`,
        description: '',
        tags: [],
        enabled: true,
        sampling_rate: 0.1,
        scanner_type: 'monitor',
        scanner_config: { prompt: 'p' },
    })

    const observation = (id: string, scannerId: string): Record<string, any> => ({
        id,
        scanner_id: scannerId,
        session_id: `session-${id}`,
        status: 'succeeded',
        created_at: '2026-05-12T00:00:00Z',
    })

    const setVariant = (variant: string): void => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.REPLAY_VISION_HOME_REDESIGN_EXPERIMENT], {
            [FEATURE_FLAGS.REPLAY_VISION_HOME_REDESIGN_EXPERIMENT]: variant,
        })
    }

    beforeEach(() => {
        // featureFlagLogic persists to localStorage, so a variant set in one test would leak
        // into the next test's fresh kea context.
        localStorage.clear()
        recentSpy = jest.fn(() => [
            200,
            { results: [observation('o1', 'a'), observation('o2', 'a'), observation('o3', 'b')] },
        ])
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': {
                    results: [scannerRow('a'), scannerRow('b')],
                    count: 2,
                },
                '/api/projects/:team/vision/scanners/recent_observations/': recentSpy,
                '/api/projects/:team/vision/scanners/creators/': { creators: [] },
                '/api/projects/:team/tags': [],
            },
        })
        initKeaTests()
        logic = scannerHighlightsLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('fetches after a scanner page load in highlights mode and groups by scanner', async () => {
        setVariant('test')
        await expectLogic(logic, () => {
            replayScannersLogic.actions.loadScanners()
        })
            .toDispatchActions(['loadScannersSuccess', 'loadRecentObservations', 'loadRecentObservationsSuccess'])
            .toFinishAllListeners()
        expect(logic.values.recentObservations).toEqual({
            a: [expect.objectContaining({ id: 'o1' }), expect.objectContaining({ id: 'o2' })],
            b: [expect.objectContaining({ id: 'o3' })],
        })
    })

    it('never fetches while the classic list is active', async () => {
        setVariant('control')
        await expectLogic(logic, () => {
            replayScannersLogic.actions.loadScanners()
        })
            .toDispatchActions(['loadScannersSuccess'])
            .toFinishAllListeners()
        expect(recentSpy).not.toHaveBeenCalled()
        expect(logic.values.recentObservations).toBeNull()
    })

    it('flags a failed fetch and clears the flag on retry', async () => {
        setVariant('test')
        recentSpy.mockImplementation(() => [500, { detail: 'nope' }])
        // Load a scanner page first: with no scanners on the page the loader answers {} without a request.
        await expectLogic(logic, () => {
            replayScannersLogic.actions.loadScanners()
        })
            .toDispatchActions(['loadRecentObservationsFailure'])
            .toMatchValues({ recentObservationsFailed: true })
        recentSpy.mockImplementation(() => [200, { results: [] }])
        await expectLogic(logic, () => {
            logic.actions.loadRecentObservations()
        })
            .toDispatchActions(['loadRecentObservationsSuccess'])
            .toMatchValues({ recentObservationsFailed: false })
    })
})
