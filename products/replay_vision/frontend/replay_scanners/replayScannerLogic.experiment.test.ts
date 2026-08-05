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

    it('remove clears the context and strips the managed exposure filter from the query', async () => {
        expect(logic.values.scanner.query?.events).toHaveLength(1)

        await expectLogic(logic, () => logic.actions.removeExperimentTargeting()).toDispatchActions([
            'removeExperimentTargeting',
            'detachExperimentContext',
        ])

        expect(logic.values.experimentContext).toBeNull()
        expect(logic.values.scanner.query?.events).toEqual([])
        expect(logic.values.scanner.query?.properties).toEqual([])
    })

    it('variant changes recompile the exposure filter in the stored query', async () => {
        await expectLogic(logic, () => logic.actions.setExperimentVariantKeys(['control']))
        const exposureEvent = logic.values.scanner.query?.events?.[0] as { properties: { value: unknown }[] }
        expect(exposureEvent.properties[0]).toMatchObject({ value: ['control'] })
    })

    it('query prefill matches the compiled experiment query', () => {
        expect(logic.values.scanner.query).toEqual(buildExperimentScannerQuery(experiment, ['test'], false))
    })
})
