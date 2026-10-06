import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ExperimentVariantsReadoutApi, VariantsAnalysisStateApi } from '../generated/api.schemas'
import {
    UNATTRIBUTED_VARIANT,
    scannerVariantsLogic,
    variantComparisonState,
    variantObservationsUrl,
} from './scannerVariantsLogic'

const analysis = (overrides: Partial<VariantsAnalysisStateApi>): VariantsAnalysisStateApi => ({
    scout_config_id: 'scout-1',
    scout_enabled: true,
    recorded_at: '2026-10-02T09:00:00Z',
    scanner_version: 2,
    current: true,
    ...overrides,
})

const readout: ExperimentVariantsReadoutApi = {
    experiment: null,
    window: { total_observations: 3, first_observation_at: null, last_observation_at: null },
    variants: [],
    differences: null,
    unattributed_count: 0,
    analysis: null,
}

describe('scannerVariantsLogic', () => {
    it.each([
        ['no scout', null, false, 'no_scout'],
        // The scout list can know about a scout the readout loaded before, and the CTA must not offer a second.
        ['a scout the readout has not seen yet', null, true, 'pending'],
        ['a scout that has not run', analysis({ recorded_at: null }), true, 'pending'],
        ['an analysis of an older scanner version', analysis({ current: false }), true, 'updating'],
        ['a current analysis', analysis({}), true, 'ready'],
    ] as const)('reads %s as %s', (_name, state, hasScout, expected) => {
        expect(variantComparisonState(state, hasScout)).toBe(expected)
    })

    // The readout counts only succeeded observations, but every observation that has not succeeded
    // also has no variant, so the "No variant" link must narrow to succeeded ones to match its count.
    it.each([
        ['a variant', 'control', null],
        ['no variant', UNATTRIBUTED_VARIANT, 'succeeded'],
    ])('links %s to the observations its count reads', (_name, variantKey, expectedStatus) => {
        const params = new URL(variantObservationsUrl('scanner-1', variantKey), 'http://localhost').searchParams

        expect(params.get('variant')).toBe(variantKey)
        expect(params.get('status')).toBe(expectedStatus)
    })

    it('reports one tab view per mount, not one per reload', async () => {
        useMocks({ get: { '/api/projects/:team/vision/scanners/:id/variants/': () => [200, readout] } })
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')
        const logic = scannerVariantsLogic({ scannerId: 'scanner-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadReadoutSuccess']).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadReadout()).toFinishAllListeners()

        const views = captureSpy.mock.calls.filter(([event]) => event === 'replay_vision_variants_tab_viewed')
        expect(views).toEqual([
            [
                'replay_vision_variants_tab_viewed',
                expect.objectContaining({ scanner_id: 'scanner-1', comparison_state: 'no_scout', variant_count: 0 }),
            ],
        ])
        logic.unmount()
    })
})
