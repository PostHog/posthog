import { describe, expect, it } from 'vitest'

import { ExperimentExposureQuerySchema } from '@/schema/experiments'

describe('Experiment exposure query schema', () => {
    // getExposures round-trips the stored exposure_criteria through this hand-written schema,
    // and Zod 4 z.object strips unknown keys on parse, so a criteria field missing from the
    // schema silently degrades the query the backend receives.
    it('keeps every stored exposure_criteria field through a parse round-trip', () => {
        const exposureCriteria = {
            filterTestAccounts: true,
            exposure_config: {
                kind: 'ExperimentEventExposureConfig',
                event: '$feature_flag_called',
                properties: [],
            },
            activation_config: {
                kind: 'ExperimentEventExposureConfig',
                event: 'activated',
                properties: [],
            },
            multiple_variant_handling: 'exclude',
        }

        const parsed = ExperimentExposureQuerySchema.parse({
            kind: 'ExperimentExposureQuery',
            experiment_id: 1,
            experiment_name: 'test',
            exposure_criteria: exposureCriteria,
        })

        expect(parsed.exposure_criteria).toEqual(exposureCriteria)
    })
})
