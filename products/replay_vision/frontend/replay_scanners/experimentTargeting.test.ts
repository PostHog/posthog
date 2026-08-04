import { Experiment, PropertyFilterType, PropertyOperator } from '~/types'

import {
    buildExperimentScannerQuery,
    experimentScannerName,
    experimentScannerParams,
    parseExperimentScannerParams,
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
    it.each([
        [{ experimentId: 7, variantKeys: [], useExposureFallback: false }],
        [{ experimentId: 7, variantKeys: ['test'], useExposureFallback: false }],
        [{ experimentId: 7, variantKeys: ['control', 'test'], useExposureFallback: true }],
    ])('deep-link params round-trip through the parser: %j', (params) => {
        expect(parseExperimentScannerParams(experimentScannerParams(params))).toEqual(params)
    })

    it.each([[{}], [{ experiment: 'not-a-number' }], [{ experiment: '-3' }], [{ variants: 'test' }]])(
        'params without a valid experiment id parse as null: %j',
        (searchParams) => {
            expect(parseExperimentScannerParams(searchParams)).toBeNull()
        }
    )

    it('compiles the default exposure event filter with the selected variants', () => {
        const query = buildExperimentScannerQuery(experiment, ['test'], false)
        expect(query.events).toEqual([
            expect.objectContaining({
                id: '$feature_flag_called',
                properties: [
                    {
                        key: '$feature_flag_response',
                        type: PropertyFilterType.Event,
                        value: ['test'],
                        operator: PropertyOperator.Exact,
                    },
                    {
                        key: '$feature_flag',
                        type: PropertyFilterType.Event,
                        value: ['checkout-redesign'],
                        operator: PropertyOperator.Exact,
                    },
                ],
            }),
        ])
        expect(query.filter_test_accounts).toBe(true)
    })

    it('targets every variant when no subset is selected', () => {
        const query = buildExperimentScannerQuery(experiment, [], false)
        expect(query.events?.[0]?.properties?.[0]).toMatchObject({
            key: '$feature_flag_response',
            value: ['control', 'test'],
        })
    })

    it('compiles the flag-value property filter in fallback mode', () => {
        const query = buildExperimentScannerQuery(experiment, ['test'], true)
        expect(query.events).toEqual([])
        expect(query.properties).toEqual([
            {
                key: '$feature/checkout-redesign',
                type: PropertyFilterType.Event,
                value: ['test'],
                operator: PropertyOperator.Exact,
            },
        ])
    })

    it('never persists playlist-only query fields', () => {
        const query = buildExperimentScannerQuery(experiment, [], false)
        expect(Object.keys(query)).toEqual(
            expect.not.arrayContaining(['date_from', 'date_to', 'order', 'session_ids', 'limit'])
        )
    })

    it.each([
        ['Frustration score', 'Checkout redesign', 'Frustration score: Checkout redesign'],
        ['', 'Checkout redesign', 'Checkout redesign'],
        ['Base', 'x'.repeat(300), `Base: ${'x'.repeat(249)}`],
    ])('experimentScannerName(%j, …) fits the 255-char model limit', (base, experimentName, expected) => {
        expect(experimentScannerName(base, experimentName)).toEqual(expected)
    })
})
