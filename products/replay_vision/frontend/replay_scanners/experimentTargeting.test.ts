import { RecordingsQuery } from '~/queries/schema/schema-general'
import { Experiment, PropertyFilterType, PropertyOperator } from '~/types'

import {
    applyExperimentVariant,
    buildExperimentScannerQuery,
    experimentScannerName,
    experimentScannerParams,
    parseExperimentScannerParams,
    reconcileVariantKey,
} from './experimentTargeting'

const experiment = {
    id: 7,
    name: 'Checkout redesign',
    feature_flag_key: 'checkout-redesign',
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

describe('experimentTargeting', () => {
    it.each([[{ experimentId: 7, variantKey: null }], [{ experimentId: 7, variantKey: 'test' }]])(
        'deep-link params round-trip through the parser: %j',
        (params) => {
            expect(parseExperimentScannerParams(experimentScannerParams(params))).toEqual(params)
        }
    )

    it.each([
        [{}],
        [{ experiment: 'not-a-number' }],
        [{ experiment: '-3' }],
        [{ variant: 'test' }],
        // kea-router coerces `?experiment=true` to boolean true, and Number(true) is 1; without a
        // type guard that would prefill experiment 1 rather than parse as null.
        [{ experiment: true }],
        [{ experiment: false }],
    ])('params without a valid experiment id parse as null: %j', (searchParams) => {
        expect(parseExperimentScannerParams(searchParams)).toBeNull()
    })

    it.each([
        // kea-router hands single numeric query values back as numbers, not strings. The router
        // values, not the stringified ones experimentScannerParams emits, are what the parser sees.
        [{ experiment: 7 }, { experimentId: 7, variantKey: null }],
        [
            { experiment: 7, variant: 1 },
            { experimentId: 7, variantKey: '1' },
        ],
    ])('parses raw router values (numbers, not strings): %j', (searchParams, expected) => {
        expect(parseExperimentScannerParams(searchParams)).toEqual(expected)
    })

    it.each([
        // No selection means all variants, so null stays null.
        [null, null],
        // A valid variant survives.
        ['test', 'test'],
        // A stale key the experiment no longer has drops to all variants rather than an impossible target.
        ['old-variant', null],
    ])('reconciles the requested variant key against the experiment: %j', (requested, expected) => {
        expect(reconcileVariantKey(experiment, requested)).toEqual(expected)
    })

    it('targets the experiment person-scoped, with the selected variant', () => {
        const query = buildExperimentScannerQuery(experiment, 'test')
        expect(query.experiment_exposure).toEqual({ experiment_id: 7, variant: 'test' })
        expect(query.filter_test_accounts).toBe(true)
    })

    it('omits the variant when targeting all variants', () => {
        const query = buildExperimentScannerQuery(experiment, null)
        expect(query.experiment_exposure).toEqual({ experiment_id: 7 })
    })

    it('never persists playlist-only query fields', () => {
        const query = buildExperimentScannerQuery(experiment, null)
        expect(Object.keys(query)).toEqual(
            expect.not.arrayContaining(['date_from', 'date_to', 'order', 'session_ids', 'limit'])
        )
    })

    it('a variant change rewrites only experiment_exposure, keeping user-added filters', () => {
        const userFilter = {
            key: '$browser',
            type: PropertyFilterType.Event,
            value: ['Chrome'],
            operator: PropertyOperator.Exact,
        }
        const edited = {
            ...buildExperimentScannerQuery(experiment, 'test'),
            properties: [userFilter],
        } as RecordingsQuery

        const updated = applyExperimentVariant(edited, { experiment, variantKey: 'control' })

        expect(updated.experiment_exposure).toEqual({ experiment_id: 7, variant: 'control' })
        expect(updated.properties).toEqual([userFilter])
    })

    it.each([
        ['Frustration score', 'Checkout redesign', 'Frustration score: Checkout redesign'],
        ['', 'Checkout redesign', 'Checkout redesign'],
        ['Base', 'x'.repeat(300), `Base: ${'x'.repeat(249)}`],
    ])('experimentScannerName(%j, …) fits the 255-char model limit', (base, experimentName, expected) => {
        expect(experimentScannerName(base, experimentName)).toEqual(expected)
    })
})
