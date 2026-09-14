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

    // The backend defaults `kind` and accepts `properties` omitted on write, and API clients
    // clear a config with an explicit null, so stored criteria carry all three shapes. A read
    // schema stricter than the store fails every results read for those experiments.
    it('accepts a stored exposure config without kind or properties, filling the backend defaults', () => {
        const parsed = ExperimentExposureQuerySchema.parse({
            kind: 'ExperimentExposureQuery',
            experiment_id: 1,
            experiment_name: 'test',
            exposure_criteria: { exposure_config: { event: '$pageview' } },
        })

        expect(parsed.exposure_criteria?.exposure_config).toEqual({
            kind: 'ExperimentEventExposureConfig',
            event: '$pageview',
            properties: [],
        })
    })

    it('accepts a stored exposure config with null kind or properties, filling the backend defaults', () => {
        const parsed = ExperimentExposureQuerySchema.parse({
            kind: 'ExperimentExposureQuery',
            experiment_id: 1,
            experiment_name: 'test',
            exposure_criteria: { exposure_config: { kind: null, event: '$pageview', properties: null } },
        })

        expect(parsed.exposure_criteria?.exposure_config).toEqual({
            kind: 'ExperimentEventExposureConfig',
            event: '$pageview',
            properties: [],
        })
    })

    it('accepts explicit null exposure and activation configs', () => {
        const parsed = ExperimentExposureQuerySchema.parse({
            kind: 'ExperimentExposureQuery',
            experiment_id: 1,
            experiment_name: 'test',
            exposure_criteria: { exposure_config: null, activation_config: null, filterTestAccounts: false },
        })

        expect(parsed.exposure_criteria).toEqual({
            exposure_config: null,
            activation_config: null,
            filterTestAccounts: false,
        })
    })

    it('still routes an action-based config to the ActionsNode branch', () => {
        const parsed = ExperimentExposureQuerySchema.parse({
            kind: 'ExperimentExposureQuery',
            experiment_id: 1,
            experiment_name: 'test',
            exposure_criteria: { exposure_config: { kind: 'ActionsNode', id: 5 } },
        })

        expect(parsed.exposure_criteria?.exposure_config).toEqual({ kind: 'ActionsNode', id: 5 })
    })

    it('still rejects an event config with no event', () => {
        expect(
            ExperimentExposureQuerySchema.safeParse({
                kind: 'ExperimentExposureQuery',
                experiment_id: 1,
                experiment_name: 'test',
                exposure_criteria: { exposure_config: { properties: [] } },
            }).success
        ).toBe(false)
    })
})
