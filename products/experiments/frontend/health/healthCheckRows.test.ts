import type { ExperimentHealthCheckResultApi } from '../generated/api.schemas'
import { healthCheckRowsTable, healthDetectableEffects } from './healthCheckRows'

const check = (
    key: ExperimentHealthCheckResultApi['key'],
    rows: ExperimentHealthCheckResultApi['rows']
): ExperimentHealthCheckResultApi => ({
    key,
    name: 'Check',
    description: 'Looks for something.',
    status: 'passed',
    reason: null,
    values: {},
    rule: null,
    rows,
})

describe('healthCheckRows', () => {
    it.each([
        {
            name: 'a change before the first exposure moved nobody',
            row: { changed_at: '2026-10-19T07:05:00Z', before_exposure: true },
            effect: 'Saved before anyone was exposed, so it moved nobody',
        },
        {
            name: 'an unknown exposure answer says so',
            row: { changed_at: '2026-10-24T12:10:00Z', before_exposure: null },
            effect: "Couldn't tell whether anyone was exposed before it",
        },
        {
            name: 'a change after the first exposure says only that',
            row: { changed_at: '2026-10-24T12:10:00Z', before_exposure: false },
            effect: 'Saved after users were exposed',
        },
    ])('healthCheckRowsTable: $name', ({ row, effect }) => {
        const before = 'Set 1: 100%'
        const after = 'Set 1: 50%'
        const table = healthCheckRowsTable(
            check('release_conditions_changed_mid_run', [{ ...row, before, after }]),
            'users'
        )

        expect(table?.rows).toEqual([
            {
                saved: { time: row.changed_at },
                before: { text: before },
                after: { text: after },
                effect: { text: effect },
            },
        ])
    })

    it('healthCheckRowsTable: a bucketing change names its setting', () => {
        const table = healthCheckRowsTable(
            check('bucketing_changed_mid_run', [
                {
                    changed_at: '2026-10-24T12:10:00Z',
                    changed_setting: 'Match by',
                    before: 'user ID',
                    after: 'device ID',
                    before_exposure: false,
                },
            ]),
            'users'
        )

        expect(table?.columns.map(({ title }) => title)).toEqual(['Saved', 'Setting', 'Before', 'After', 'Effect'])
        expect(table?.rows[0].setting).toEqual({ text: 'Match by' })
    })

    it('healthCheckRowsTable: a metric event without a record reads as unknown', () => {
        const metric = { metric_name: 'Checkout', metric_role: 'primary', ratio_side: null }
        const table = healthCheckRowsTable(
            check('metric_event_not_ingested', [
                { ...metric, event: 'cart', event_received: true },
                { ...metric, event: 'pay', event_received: false },
                { ...metric, event: 'refund', event_received: null },
            ]),
            'users'
        )

        expect(table?.rows.map(({ metric, event, received }) => [metric, event, received])).toEqual([
            [{ text: 'Checkout (primary)' }, { text: 'cart' }, { text: 'Yes' }],
            [{ text: 'Checkout (primary)' }, { text: 'pay' }, { text: 'No' }],
            [{ text: 'Checkout (primary)' }, { text: 'refund' }, { text: 'Unknown' }],
        ])
    })

    it('healthCheckRowsTable: a difference carries its sign', () => {
        const table = healthCheckRowsTable(
            check('early_significance', [
                {
                    variant: 'test',
                    difference_percentage: 14.2,
                    detectable_difference_percentage: 9.8,
                    significant: true,
                },
                {
                    variant: 'test-2',
                    difference_percentage: -3.1,
                    detectable_difference_percentage: 9.9,
                    significant: false,
                },
            ]),
            'users'
        )

        expect(table?.rows.map((row) => [row.difference, row.significant])).toEqual([
            [{ text: '+14.2%' }, { text: 'Yes' }],
            [{ text: '-3.1%' }, { text: 'No' }],
        ])
    })

    it('healthDetectableEffects: only significant variants, on one scale', () => {
        const effects = healthDetectableEffects(
            check('early_significance', [
                {
                    variant: 'test',
                    difference_percentage: 14.2,
                    detectable_difference_percentage: 9.8,
                    significant: true,
                },
                {
                    variant: 'test-2',
                    difference_percentage: -21,
                    detectable_difference_percentage: 10.4,
                    significant: true,
                },
                {
                    variant: 'test-3',
                    difference_percentage: 40,
                    detectable_difference_percentage: 9.9,
                    significant: false,
                },
            ])
        )

        expect(effects).toEqual([
            { variant: 'test', difference: 14.2, detectable: 9.8, scaleMax: 30 },
            { variant: 'test-2', difference: -21, detectable: 10.4, scaleMax: 30 },
        ])
    })
})
