import { RecordingsQuery } from '~/queries/schema/schema-general'
import { Experiment, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import {
    buildExperimentScannerQuery,
    experimentScannerName,
    experimentScannerParams,
    parseExperimentScannerParams,
    reconcileVariantKeys,
    replaceExperimentExposureFilter,
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

    it.each([
        [{}],
        [{ experiment: 'not-a-number' }],
        [{ experiment: '-3' }],
        [{ variants: 'test' }],
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
        [{ experiment: 7 }, { experimentId: 7, variantKeys: [], useExposureFallback: false }],
        [
            { experiment: 7, variants: 1 },
            { experimentId: 7, variantKeys: ['1'], useExposureFallback: false },
        ],
        [
            { experiment: '7', variants: '1,2' },
            { experimentId: 7, variantKeys: ['1', '2'], useExposureFallback: false },
        ],
    ])('parses raw router values (numbers, not strings): %j', (searchParams, expected) => {
        expect(parseExperimentScannerParams(searchParams)).toEqual(expected)
    })

    it.each([
        // No selection means every variant, so an empty request stays empty.
        [[], []],
        // A stale key that the experiment no longer has is dropped rather than persisted.
        [['test', 'old-variant'], ['test']],
        // When every requested key is unknown, fall back to the full variant set rather than the
        // empty list that would broaden to an IsSet filter matching every enrolled session.
        [['old-variant'], ['control', 'test']],
    ])('reconciles requested variant keys against the experiment: %j', (requested, expected) => {
        expect(reconcileVariantKeys(experiment, requested)).toEqual(expected)
    })

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

    it('variant changes swap the exposure filter and keep user-added filters', () => {
        const initial = buildExperimentScannerQuery(experiment, ['test'], false)
        const userFilter = {
            key: '$browser',
            type: PropertyFilterType.Event,
            value: ['Chrome'],
            operator: PropertyOperator.Exact,
        }
        const edited = { ...initial, properties: [userFilter] } as RecordingsQuery

        const updated = replaceExperimentExposureFilter(edited, {
            experiment,
            variantKeys: ['control'],
            useExposureFallback: false,
        })

        expect(updated.events?.[0]?.properties?.[0]).toMatchObject({
            key: '$feature_flag_response',
            value: ['control'],
        })
        expect(updated.properties).toEqual([userFilter])
    })

    it('fallback-mode variant changes keep user event filters and swap only the flag property', () => {
        const initial = buildExperimentScannerQuery(experiment, ['test'], true)
        const userEvent = { id: '$pageview', name: '$pageview', type: 'events' }
        const edited = { ...initial, events: [userEvent] } as RecordingsQuery

        const updated = replaceExperimentExposureFilter(edited, {
            experiment,
            variantKeys: ['control'],
            useExposureFallback: true,
        })

        expect(updated.events).toEqual([expect.objectContaining({ id: '$pageview' })])
        expect(updated.properties).toEqual([
            expect.objectContaining({ key: '$feature/checkout-redesign', value: ['control'] }),
        ])
    })

    it('forces AND when swapping the exposure filter into an OR query', () => {
        const orQuery = {
            ...buildExperimentScannerQuery(experiment, ['test'], false),
            operand: FilterLogicalOperator.Or,
        } as RecordingsQuery
        const updated = replaceExperimentExposureFilter(orQuery, {
            experiment,
            variantKeys: ['test'],
            useExposureFallback: false,
        })
        expect(updated.operand).toEqual(FilterLogicalOperator.And)
    })

    it('inserts the exposure filter when the user removed it', () => {
        const emptied = replaceExperimentExposureFilter(
            { ...buildExperimentScannerQuery(experiment, [], false), events: [] },
            { experiment, variantKeys: ['test'], useExposureFallback: false }
        )
        expect(emptied.events).toHaveLength(1)
        expect(emptied.events?.[0]?.properties?.[0]).toMatchObject({ value: ['test'] })
    })

    it.each([
        ['Frustration score', 'Checkout redesign', 'Frustration score: Checkout redesign'],
        ['', 'Checkout redesign', 'Checkout redesign'],
        ['Base', 'x'.repeat(300), `Base: ${'x'.repeat(249)}`],
    ])('experimentScannerName(%j, …) fits the 255-char model limit', (base, experimentName, expected) => {
        expect(experimentScannerName(base, experimentName)).toEqual(expected)
    })
})
