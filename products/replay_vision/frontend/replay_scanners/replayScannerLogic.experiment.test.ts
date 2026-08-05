import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { buildExperimentScannerQuery, prefillScannerForExperiment } from './experimentTargeting'
import { replayScannerLogic } from './replayScannerLogic'
import { newScanner } from './scannerTemplates'

const experiment = {
    id: 9,
    name: 'test test',
    feature_flag_key: 'test-test',
    feature_flag: {
        filters: {
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        },
    },
    exposure_criteria: { filterTestAccounts: true },
} as unknown as Experiment

describe('replayScannerLogic experiment targeting', () => {
    let logic: ReturnType<typeof replayScannerLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team/vision/scanners/estimate/': { matched_sessions: 0 },
            },
        })
        initKeaTests()
        logic = replayScannerLogic({ id: 'new' })
        logic.mount()
        const context = { experiment, variantKeys: ['test'], useExposureFallback: false }
        logic.actions.setExperimentContext(context)
        logic.actions.setScannerValues(prefillScannerForExperiment(newScanner(null), context))
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('remove clears the context, the persisted experiment_targeting, and the managed exposure filter', async () => {
        expect(logic.values.scanner.query?.events).toHaveLength(1)
        expect(logic.values.scanner.experiment_targeting).toMatchObject({ experiment_id: 9 })

        await expectLogic(logic, () => logic.actions.removeExperimentTargeting()).toDispatchActions([
            'removeExperimentTargeting',
            'detachExperimentContext',
        ])

        expect(logic.values.experimentContext).toBeNull()
        expect(logic.values.scanner.experiment_targeting).toBeNull()
        expect(logic.values.scanner.query?.events).toEqual([])
        expect(logic.values.scanner.query?.properties).toEqual([])
    })

    it('variant changes recompile the exposure filter and the persisted experiment_targeting', async () => {
        await expectLogic(logic, () => logic.actions.setExperimentVariantKeys(['control']))
        const exposureEvent = logic.values.scanner.query?.events?.[0] as { properties: { value: unknown }[] }
        expect(exposureEvent.properties[0]).toMatchObject({ value: ['control'] })
        expect(logic.values.scanner.experiment_targeting).toMatchObject({ variant_keys: ['control'] })
    })

    it('editing a saved scanner with a experiment_targeting rehydrates the targeting card', async () => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/saved-1/': {
                    ...newScanner(null),
                    id: 'saved-1',
                    name: 'Saved scanner',
                    experiment_targeting: {
                        experiment_id: 9,
                        variant_keys: ['test'],
                        use_exposure_fallback: false,
                    },
                },
                '/api/projects/:team/vision/scanners/:id/observations/': { results: [] },
                '/api/projects/:team/vision/scanners/:id/observations/stats/': {
                    status_counts: { total: 0, succeeded: 0, failed: 0, ineligible: 0, in_flight: 0 },
                    coverage: { recent_sessions: 0, total_sessions: 0, recent_days: 14 },
                    available_tags: [],
                },
                '/api/projects/:team/experiments/9/': experiment,
            },
        })
        const savedLogic = replayScannerLogic({ id: 'saved-1' })
        savedLogic.mount()
        try {
            await expectLogic(savedLogic).toDispatchActions(['loadScannerSuccess', 'setExperimentContext'])
            expect(savedLogic.values.experimentContext).toMatchObject({
                variantKeys: ['test'],
                experiment: { id: 9 },
            })
        } finally {
            savedLogic.unmount()
        }
    })

    it('query prefill matches the compiled experiment query', () => {
        expect(logic.values.scanner.query).toEqual(buildExperimentScannerQuery(experiment, ['test'], false))
    })
})
